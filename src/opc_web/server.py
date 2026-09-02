# -*- coding: utf-8 -*-
"""HTTP 服务：路由与请求处理（标准库 http.server，零第三方依赖）。"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote

from . import bootstrap, config, knowledge, parsers, review, roles, runner, scheduler, store


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _body(self):
        """读取 POST body 并解析 JSON；空 body 返回 {}；解析失败返回 None。"""
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return None

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, p, ctype):
        try:
            data = p.read_bytes()
        except OSError:
            self.send_error(404, "Not Found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = self.path.split("?", 1)[0]
        if url == "/":
            self._file(config.TEMPLATES / "index.html", "text/html; charset=utf-8")
        elif url.startswith("/static/"):
            rel = url[len("/static/"):]
            ctype = "text/css; charset=utf-8" if rel.endswith(".css") else "text/javascript; charset=utf-8"
            self._file(config.STATIC / rel, ctype)
        elif url == "/api/kb-entries":
            self._json({"ok": True, "manager": "老板助理（枢纽）R1",
                        "entries": knowledge.kb_entries()})
        elif url == "/api/md":
            qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            rel = unquote(qs.get("rel", [""])[0])
            try:
                self._json({"ok": True, "rel": rel, "text": knowledge.read_md(rel)})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 400)
        elif url == "/api/pending":
            try:
                data = parsers.parse_piyuetai(knowledge.read_md(config.PIYUETAI_REL))
                self._json({"ok": True, "work": data["work"], "pending": data["pending"],
                            "archive": data["archive"]})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/summary":
            try:
                data = parsers.parse_piyuetai(knowledge.read_md(config.PIYUETAI_REL))
                self._json({"ok": True,
                            "pendingCount": len(data["pending"]),
                            "workCount": len(data["work"]),
                            "archiveCount": len(data["archive"]), "daily": knowledge.latest_daily()})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/org":
            try:
                self._json({"ok": True, "roles": parsers.parse_roles()})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/timeline":
            try:
                self._json({"ok": True, "events": parsers.parse_timeline()})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/queue":
            try:
                self._json({"ok": True, "queue": store.tasks()})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/rn-outputs":
            try:
                qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                self._json({"ok": True, "groups": scheduler.rn_outputs(qs.get("no", [""])[0])})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/ws-files":
            try:
                self._json({"ok": True, "files": scheduler.ws_files()})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/tokens":
            try:
                self._json({"ok": True, "rows": scheduler.token_rows()})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/ws-file":
            try:
                qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                rel = unquote(qs.get("rel", [""])[0]).strip()
                if not rel:
                    self._json({"ok": False, "msg": "缺少文件路径"}, 400)
                    return
                self._json({"ok": True, **scheduler.ws_read(rel)})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 400)
        elif url == "/api/plan-rows":
            try:
                self._json({"ok": True, "rows": store.subtasks()})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/task-output":
            try:
                qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                no = unquote(qs.get("no", [""])[0]).strip()
                if not no:
                    self._json({"ok": False, "msg": "缺少任务编号 no"}, 400)
                    return
                self._json({"ok": True, **scheduler.task_output(no)})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/sub-output":
            try:
                qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                no = unquote(qs.get("no", [""])[0]).strip()
                if not no:
                    self._json({"ok": False, "msg": "缺少子任务编号 no"}, 400)
                    return
                res = scheduler.sub_output(no)
                if not res:
                    self._json({"ok": False, "msg": "未找到子任务产出 " + no}, 404)
                    return
                self._json({"ok": True, "no": no, **res})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
        elif url == "/api/scheduler":
            self._json({"ok": True, "state": scheduler.SCHED_STATE})
        elif url == "/api/roles":
            self._json({"ok": True, "roles": [{"no": no, "name": name} for no, name in roles.role_files()]})
        elif url == "/api/roles/card":
            qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            no = unquote(qs.get("no", [""])[0])
            p = config.AGENTS_DIR / (no + ".role.md")
            if not p.exists():
                self._json({"ok": False, "msg": "角色不存在"}, 404)
                return
            self._json({"ok": True, "no": no, "card": config.read_text(p)})
        elif url == "/api/projects":
            self._json({"ok": True, "projects": config.projects(),
                        "active": config.active_project(), "seedRoles": config.settings_info()["seedRoles"]})
        elif url == "/api/settings":
            self._json(config.settings_info())
        elif url == "/api/schedule":
            self._json({"ok": True, "schedules": config.schedule_status()})
        elif url == "/api/dirs":
            qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            path = unquote(qs.get("path", [""])[0])
            self._json(config.list_dirs(path))
        elif url == "/api/run/events":
            qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            since = int(qs.get("since", ["0"])[0] or 0)
            self._json(runner.events(since))
        else:
            self._json({"ok": False, "msg": "未知接口"}, 404)

    def do_POST(self):
        url = self.path.split("?", 1)[0]
        if url == "/api/retry":
            body = self._body()
            if body is None:
                self._json({"ok": False, "msg": "JSON 解析失败"}, 400)
                return
            no = str(body.get("no", "")).strip()
            if not no:
                self._json({"ok": False, "msg": "缺少任务编号 no"}, 400)
                return
            hit = [t for t in store.tasks() if t["no"] == no]
            if not hit:
                self._json({"ok": False, "msg": "任务 " + no + " 不在队列中"}, 404)
                return
            retried = False
            if hit[0]["status"] == "阻塞":
                store.set_task(no, "待派")
                retried = True
                scheduler.scan_once()  # 立即扫描：置待派后马上重启执行链（busy 时自然排队）
            self._json({"ok": True, "no": no, "retried": retried,
                        "queue": store.tasks(),
                        "msg": ("重试 " + no + "：已重置为待派并触发扫描") if retried
                               else (no + " 状态为「" + hit[0]["status"] + "」，无需重试")})
            return
        if url == "/api/dispatch":
            body = self._body()
            if body is None:
                self._json({"ok": False, "msg": "JSON 解析失败"}, 400)
                return
            text = str(body.get("task", "")).strip()
            expect = str(body.get("expect", "R1 判断")).strip()
            if not text:
                self._json({"ok": False, "msg": "任务内容不能为空"}, 400)
                return
            no = store.add_task(text, expect)
            scheduler.scan_once()  # 立即生成 R1 拆解指令，不等 8s 轮询
            self._json({"ok": True, "no": no, "queue": store.tasks(), "state": scheduler.SCHED_STATE})
            return
        if url == "/api/task-delete":
            body = self._body()
            if body is None:
                self._json({"ok": False, "msg": "JSON 解析失败"}, 400)
                return
            no = str(body.get("no", "")).strip()
            if not no:
                self._json({"ok": False, "msg": "缺少任务编号 no"}, 400)
                return
            if not any(t["no"] == no for t in store.tasks()):
                self._json({"ok": False, "msg": "任务 " + no + " 不在队列中"}, 404)
                return
            st = scheduler.SCHED_STATE
            if st.get("busy") and no in (st.get("tag") or ""):
                self._json({"ok": False, "msg": no + " 正在执行中，暂不可删除"}, 409)
                return
            store.delete_task(no)
            removed = scheduler.clean_task_files(no)
            self._json({"ok": True, "no": no, "removedFiles": removed, "queue": store.tasks(),
                        "msg": "已删除任务 " + no + ((" · 清理工作区文件 " + str(removed) + " 个") if removed else "")})
            return
        if url == "/api/r1-archive":
            try:
                self._json({"ok": True, "result": scheduler.r1_archive()})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
            return
        if url == "/api/plan-execute":
            try:
                self._json({"ok": True, "result": scheduler.plan_execute()})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
            return
        if url == "/api/plan-pause":
            try:
                body = self._body() or {}
                act = str(body.get("action", "toggle"))
                if act == "toggle":
                    scheduler.SCHED_STATE["paused"] = not scheduler.SCHED_STATE["paused"]
                elif act == "pause":
                    scheduler.SCHED_STATE["paused"] = True
                else:
                    scheduler.SCHED_STATE["paused"] = False
                p = scheduler.SCHED_STATE["paused"]
                self._json({"ok": True, "paused": p,
                            "state": "已暂停：当前行跑完后停，剩余续跑（可点执行继续）" if p else "调度已恢复：可继续按派发单执行"})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
            return
        if url == "/api/roles/add":
            try:
                body = self._body() or {}
                r = roles.add_role(
                    str(body.get("name", "")).strip() or "新角色",
                    str(body.get("duty", "")).strip() or "待补充职责",
                    str(body.get("position", "")).strip() or "一句话定位",
                    str(body.get("type", "")).strip() or "业务",
                    dry=bool(body.get("dry", False)))
                if body.get("dry"):
                    self._json({"ok": True, "preview": True, "result": r})
                else:
                    self._json({"ok": True, "result": r})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
            return
        if url == "/api/roles/edit":
            try:
                body = self._body() or {}
                r = roles.edit_role(
                    str(body.get("no", "")).strip(),
                    name=str(body.get("name", "")).strip() or None,
                    duty=str(body.get("duty", "")).strip() or None,
                    position=str(body.get("position", "")).strip() or None,
                    type_=str(body.get("type", "")).strip() or None,
                    dry=bool(body.get("dry", False)))
                if body.get("dry"):
                    self._json({"ok": True, "preview": True, "result": r})
                else:
                    self._json({"ok": True, "result": r})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
            return

        if url == "/api/projects":
            # 一个端点三种动作：add / switch / remove（项目以 root 路径为唯一键）
            try:
                body = self._body() or {}
                act = str(body.get("action") or "").strip()
                root = str(body.get("root") or "").strip()
                if act in ("switch", "remove") and scheduler.SCHED_STATE.get("busy"):
                    # 切换会把 ROOT/台账/角色目录整体换掉，执行链跑一半时切会写串项目
                    self._json({"ok": False, "msg": "当前有任务正在执行，等执行链跑完再切换项目"}, 409)
                    return
                if act == "add":
                    p = config.add_project(str(body.get("name") or ""), root)
                    bootstrap.bootstrap()          # 建三目录 + 从 agents-seed 复制角色卡
                    self._json({"ok": True, "project": p, "boot": bootstrap.BOOT_LOG, **config.settings_info()})
                elif act == "switch":
                    p = config.switch_project(root)
                    bootstrap.bootstrap()
                    self._json({"ok": True, "project": p, "boot": bootstrap.BOOT_LOG, **config.settings_info()})
                elif act == "remove":
                    res = config.remove_project(root)
                    self._json({"ok": True, "result": res, **config.settings_info()})
                else:
                    self._json({"ok": False, "msg": "未知动作：" + act}, 400)
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 400)
            return
        if url == "/api/settings":
            # 一个端点服务两种保存：模型接入（body.model）与 根目录/端口（SETTING_KEYS）。
            # 原来写成两个同名分支，第二个永远走不到 —— 保存根目录会落进只处理 model 的
            # 那个分支：根目录从未写盘（界面却显示成功），还顺手把 model 段重置成默认 provider。
            try:
                body = self._body() or {}
                dry = bool(body.get("dry", False))
                kv = {k: body.get(k) for k in config.SETTING_KEYS if k in body}
                if kv.get("port") not in (None, ""):
                    try:
                        kv["port"] = int(str(kv["port"]).strip())
                    except Exception:
                        kv.pop("port", None)
                out = {"ok": True}
                if kv and not dry:
                    config.save_cfg(kv)
                    config.reload()
                    bootstrap.bootstrap()      # 新根目录下的三目录幂等重建
                    out.update(config.settings_info())
                    out["boot"] = bootstrap.BOOT_LOG
                mbody = body.get("model")
                if isinstance(mbody, dict):
                    res = config.save_model(mbody, dry=dry)
                    mi = config.model_info()
                    res["configured"] = mi["configured"]
                    res["keyMasked"] = mi["keyMasked"]
                    out["model"] = res         # 放在 settings_info 之后，否则被其 model 字段盖掉
                out["msg"] = "；".join(x for x in (
                    "模型 API 配置已保存" if isinstance(mbody, dict) else "",
                    "opc-config.json 已更新并生效" if kv else "",
                    "端口修改需重启控制台" if "port" in kv else "",
                ) if x) or "无改动"
                self._json(out)
            except Exception as e:
                self._json({"ok": False, "msg": "保存设置失败: " + str(e)[:200]}, 500)
            return
        if url == "/api/model/test":
            try:
                body = self._body() or {}
                self._json(config.test_model(body, timeout=20))
            except Exception as e:
                self._json({"ok": False, "msg": "模型连通测试异常: " + str(e)[:200]}, 500)
            return
        if url == "/api/roles/delete":
            try:
                body = self._body() or {}
                r = roles.remove_role(str(body.get("no", "")).strip())
                self._json({"ok": True, "result": r})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
            return
        if url == "/api/schedule":
            try:
                body = self._body() or {}
                action = str(body.get("action") or "add")
                jobs = config.load_schedules()
                if action == "add":
                    jobs.append({
                        "id": "sched-%d" % (len(jobs) + 1),
                        "task": str(body.get("task") or "").strip(),
                        "mode": str(body.get("mode") or "daily").strip(),
                        "time": str(body.get("time") or "").strip(),
                        "weekday": str(body.get("weekday") or "").strip(),
                        "intervalMin": str(body.get("intervalMin") or "").strip(),
                        "enabled": True,
                    })
                elif action == "toggle":
                    sid = str(body.get("id") or "")
                    for j in jobs:
                        if j.get("id") == sid:
                            j["enabled"] = not j.get("enabled", True)
                elif action == "update":
                    sid = str(body.get("id") or "")
                    for j in jobs:
                        if j.get("id") == sid:
                            for k in ("task", "mode", "time", "weekday", "intervalMin"):
                                if body.get(k) is not None:
                                    j[k] = str(body.get(k)).strip()
                            if body.get("enabled") is not None:
                                j["enabled"] = bool(body.get("enabled"))
                elif action == "delete":
                    sid = str(body.get("id") or "")
                    jobs = [j for j in jobs if j.get("id") != sid]
                else:
                    self._json({"ok": False, "msg": "未知动作：" + action}, 400)
                    return
                config.save_schedules(jobs)
                self._json({"ok": True, "schedules": config.schedule_status(jobs)})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 500)
            return
        if url == "/api/work-archive":
            try:
                body = self._body() or {}
                item = int(str(body.get("item", "0")).strip() or 0)
                if item <= 0:
                    raise ValueError("缺少工作条目编号")
                title = review.archive_work(item)
                self._json({"ok": True, "item": item, "title": title,
                            "msg": "工作 #%d「%s」已归档（标记已阅）" % (item, (title or "")[:40])})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)}, 400)
            return
        if url != "/api/piyue":
            self._json({"ok": False, "msg": "未知接口"}, 404)
            return
        body = self._body()
        if body is None:
            self._json({"ok": False, "msg": "JSON 解析失败"}, 400)
            return
        try:
            item = str(body.get("item", "")).strip()
            judge = str(body.get("judge", ""))
            opinion = str(body.get("opinion", "")).strip()
            if not item:
                raise ValueError("缺少待决编号")
            new_line = review.write_piyue(item, judge, opinion)
            # R0 采纳（批准）→ R1 自动在任务队列新建执行任务（等同在 工作台下达），
            # 并在该待决条目记录 R1 执行状态；驳回/修改不建新任务。
            extra = {}
            if review.judge_verb(judge) == "批准":
                try:
                    task_text = "执行 R0 决策（批阅台 待决 #%s）：%s" % (item, opinion or "按批阅意见执行")
                    no = store.add_task(task_text, "R1 判断")
                    review.append_r1_exec(item, "已建任务 %s，待 R1 派发执行" % no)
                    scheduler.scan_once()   # 立即生成 R1 拆解指令（与下达任务同路径）
                    extra = {"task": no}
                except Exception:
                    extra = {"task": None}
            self._json({"ok": True, "line": new_line, "item": item, **extra})
        except Exception as e:
            self._json({"ok": False, "msg": str(e)}, 400)


def create_server():
    return ThreadingHTTPServer((config.HOST, config.PORT), Handler)

