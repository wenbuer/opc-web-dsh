(function(){
  "use strict";
  var $ = function(id){ return document.getElementById(id); };
  var NL10 = String.fromCharCode(10);
  var state = { pending: [], work: [], archive: [], cur: null, daily: [], activeNo: null, activeSub: null,
                boardRows: [], runSeq: 0, runTimer: null, rolesMap: {}, lastDirPath: "", projText: null };

  function esc(s){
    s = String(s == null ? "" : s);
    return s.split("&").join("&amp;").split("<").join("&lt;").split(">").join("&gt;");
  }
  function api(url, opts){
    return fetch(url, opts || {}).then(function(r){ return r.json(); });
  }
  function cacheRoles(){
    api("/api/roles").then(function(j){
      if (j && j.ok){
        var m = state.rolesMap || {};
        (j.roles || []).forEach(function(r){ m[r.no] = r.name; });
        state.rolesMap = m;
      }
    }).catch(function(){});
  }
  function roleName(code){ return (state.rolesMap || {})[code] || code; }

  /* ---- 顶栏统计 ---- */
  function refreshStats(d){
    if (!d) return;
    $("statPending").textContent = "待裁决 " + (d.pendingCount != null ? d.pendingCount : "—");
    $("statArchived").textContent = "已批阅 " + (d.archiveCount != null ? d.archiveCount : "—");
  }

  function tick(){
    var d = new Date();
    var p = function(x){ return (x < 10 ? "0" : "") + x; };
    var el = $("clock");
    if (el) el.textContent = d.getFullYear() + "-" + p(d.getMonth()+1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  /* ================= 首页：组织架构 / 时间线 / 当前任务 ================= */
  function loadHome(){
    cacheRoles();
    api("/api/org").then(function(j){
      if (j && j.ok){ renderOrg(j.roles || []); }
      api("/api/summary").then(refreshStats).catch(function(){});
    }).catch(function(){});
    api("/api/timeline").then(function(j){
      if (j && j.ok){ renderTimeline(j.events || []); }
    }).catch(function(){});
  }
  var taskTexts = {};   // 任务编号 → 下达内容原文（左列缩略卡看不到任务文字，选中后显示在搜索栏下方）
  function showCurTask(no){
    var ct = $("curTask"), n = $("curTaskNo"), tx = $("curTaskText");
    if (!ct) return;
    if (!no){ ct.hidden = true; return; }
    if (n) n.textContent = no;
    if (tx) tx.textContent = taskTexts[no] || "（该任务内容暂未载入 —— 点击右侧任务详情查看）";
    ct.hidden = false;
  }
  function loadWorkbench(){
    state.activeNo = null;
    state.activeSub = null;
    taskTexts = {};
    showCurTask(null);
    loadQueue();
    loadBoard();
    refreshSched(0);
    renderAct(null);
    liveStart();
    var bs = $("boardSearch");
    if (bs && !bs.dataset.bound){ bs.dataset.bound = "1"; bs.addEventListener("input", renderBoard); }
  }
  /* ---- 当前任务与执行角色：默认空 —— 点击左列任务后才筛选该任务的派发行 ---- */
  function renderAct(activeNo){
    api("/api/plan-rows").then(function(j){
      if (!j || !j.ok) return;
      var box = $("actPanel");
      if (!box) return;
      if (!activeNo){
        box.innerHTML = "<div class='placeholder'>默认空——点击左列任务（T-xxx）后，此处筛选显示该任务的派发单与执行角色</div>";
        return;
      }
      var rows = (j.rows || []).filter(function(x){
        return x.no === activeNo || x.no.indexOf(activeNo + "-S") === 0;
      });
      if (!rows.length){
        box.innerHTML = "<div class='placeholder'>该任务暂无派发行（R1 未拆解或已归档）——点击左列其他任务切换</div>";
        return;
      }
      box.innerHTML = "<div class='act-ctx'>当前任务：<b>" + esc(activeNo) + "</b> · 执行角色</div><div id='actRoles' class='act-roles'></div>";
      var tagBox = $("actRoles");
      var seenRoles = {};
      (rows || []).forEach(function(x){
        if (seenRoles[x.role]) return;  // 同任务同角色只显示一个（多轮拆解累积时去重）
        seenRoles[x.role] = 1;
        var tag = document.createElement("span");
        tag.className = "act-role-tag";
        tag.title = x.sub;
        tag.innerHTML = esc(x.role) + " " + esc(roleName(x.role)) + "<em>" + esc(x.st || "") + "</em>";
        tagBox.appendChild(tag);
      });
    }).catch(function(){});
  }


  function renderOrg(roles){
    var grid = $("orgGrid");
    grid.innerHTML = "";
    var active = 0;
    (roles || []).forEach(function(r){
      if (r.code === "R0" || r.code === "R1") return;
      /* 两态：执行中亮起，其余（待命中）暗置。顶部计数只统计真正在跑的角色。 */
      var stCls = r.status === "执行中" ? "on" : "off";
      if (r.status === "执行中") active++;
      var card = document.createElement("div");
      card.className = "role-card";
      card.innerHTML = "<span class='rc-st " + stCls + "'>" + esc(r.status || "") + "</span>"
        + "<div class='rc-top'><span class='rc-name'>" + esc(r.name || r.code) + "</span><span class='rc-n'>" + esc(r.code) + "</span>"
        + "<button class='rc-folder' title='查看项目文件'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'/></svg></button><button class='rc-del' title='删除角色（需二次确认）'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 6h18'/><path d='M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2'/><path d='M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6'/><path d='M10 11v6'/><path d='M14 11v6'/></svg></button></div>"
        + "<div class='rc-duty'>" + esc(r.duty || "") + "</div>"
        + "<div class='rc-cur'>当前：" + esc(r.current || "无") + "</div>";
      card.addEventListener("click", function(){ openRole(r.code); });
      var btDel = card.querySelector(".rc-del");
      if (btDel) btDel.addEventListener("click", function(ev){ ev.stopPropagation(); openDelRoleModal(r.code, r.name || r.code); }); var btFolder = card.querySelector(".rc-folder"); if (btFolder) btFolder.addEventListener("click", function(ev){ ev.stopPropagation(); gotoRoleFiles(r.name || r.code); });
      grid.appendChild(card);
    });
    /* 原「未激活角色」位已改为固定「＋ 新增角色」入口（orgAdd）：点击弹窗新增角色；
       每张角色卡右上「编辑角色」弹窗编辑（openRoleModal("edit", code)）。
       新增/编辑均走 /api/roles/add、/api/roles/edit（角色卡 + 工作区《名称/》）。 */
  }

  function skillStem(n){ return String(n || "").replace(/\.md$/i, ""); }
  function renderSkillCaps(names){
    var body = $("roleSkillsBody");
    if (!body) return;
    body.innerHTML = "";
    if (!names || !names.length){
      body.innerHTML = "<div class='placeholder'>未装配技能 —— 点「编辑角色」在弹窗里从 agents/skills/ 勾选</div>";
      return;
    }
    names.forEach(function(n){
      var c = document.createElement("span");
      c.className = "skill-cap";
      c.textContent = skillStem(n);
      c.title = "agents/skills/" + n;
      body.appendChild(c);
    });
  }
  function openRole(code){
    var name = roleName(code);
    var tt = $("roleDetailTitle");
    if (tt) tt.textContent = name;
    var ct = $("roleCardTitle");
    var ft = $("roleFilesTitle");
    var st2 = $("roleSkillsTitle");
    if (ct) ct.textContent = code;
    if (ft) ft.textContent = name;
    if (st2) st2.textContent = name;
    var eb = $("btnEditRole"); if (eb){ eb.style.display = "inline-block"; eb.dataset.no = code; }
    var cb = $("roleCardBody");
    var sb = $("roleSkillsBody");
    if (cb) cb.innerHTML = "<div class='placeholder'>加载中…</div>";
    if (sb) sb.innerHTML = "";
    api("/api/roles/card?no=" + encodeURIComponent(code)).then(function(j){
      if (!j || !j.ok){
        cb.innerHTML = "<div class='placeholder'>角色卡不存在（本项目 agents/ 下无 " + esc(code) + ".role.md）</div>";
        renderSkillCaps([]);
        return;
      }
      cb.innerHTML = "<div class='role-card-doc'>" + renderMd(j.card || "") + "</div>";
      renderSkillCaps((parseCardFields(j.card || "").skills) || []);
    }).catch(function(e){ cb.innerHTML = "<div class='placeholder'>加载失败：" + esc(e.message) + "</div>"; renderSkillCaps([]); });
    renderRoleList(code);
  }
  function renderRoleList(code){
    var fb = $("roleFilesBody");
    if (fb) fb.innerHTML = "<div class='placeholder'>加载中…</div>";
    api("/api/rn-outputs").then(function(j){
      if (!j || !j.ok){ if (fb) fb.innerHTML = "<div class='placeholder'>产物读取失败</div>"; return; }
      var g = null, nm = roleName(code);
      (j.groups || []).forEach(function(x){
        if (x.dir === nm || x.dir === code + "-输出"){ g = x; }
      });
      if (!g){ if (fb) fb.innerHTML = "<div class='placeholder'>该角色暂无已落盘的 headless 产出（执行中或为空）</div>"; return; }
      fb.innerHTML = "";
      (g.files || []).forEach(function(f){
        var fd = document.createElement("div");
        fd.className = "rno-file";
        fd.innerHTML = "<span>" + esc(f.name) + "</span><em>" + esc(f.head.slice(0,160)) + "</em>";
        fd.addEventListener("click", function(){ showRoleFile(f.rel, code); });
        fb.appendChild(fd);
      });
    }).catch(function(e){ if (fb) fb.innerHTML = "<div class='placeholder'>异常：" + esc(e.message) + "</div>"; });
  }
  function showRoleFile(rel, code){
    var fb = $("roleFilesBody");
    var ft = $("roleFilesTitle");
    if (ft) ft.textContent = roleName(code) + " · " + rel.split("/").pop();
    if (fb) fb.innerHTML = "<div class='placeholder'>加载中…</div>";
    api("/api/md?rel=" + encodeURIComponent(rel)).then(function(j){
      if (!j || !j.ok){ if (fb) fb.innerHTML = "<div class='placeholder'>读取失败：" + esc(j && j.msg || "未知") + "</div>"; return; }
      var go = "<div class='back-bar'><a href='javascript:void(0)' id='backToFiles'>← 返回产物列表</a></div>";
      var body = "<div class='role-card-doc'>" + renderMd(j.text || "") + "</div>";
      var wrap = document.createElement("div");
      wrap.innerHTML = go + body;
      var back = wrap.querySelector("#backToFiles");
      if (back) back.addEventListener("click", function(){ if (ft) ft.textContent = roleName(code); renderRoleList(code); });
      if (fb){ fb.innerHTML = ""; fb.appendChild(wrap); }
    }).catch(function(e){ if (fb) fb.innerHTML = "<div class='placeholder'>异常：" + esc(e.message) + "</div>"; });
  }

  function renderTimeline(events){
    var box = $("timeline");
    box.innerHTML = "";
    (events || []).forEach(function(ev){
      var it = document.createElement("div");
      it.className = "tl-h-item";
      it.innerHTML = "<span class='tl-h-date'>" + esc(ev.date) + "</span>"
        + "<div class='tl-h-title'>" + esc(ev.title) + "</div>"
        + "<div class='tl-h-detail'>" + esc(ev.detail) + "</div>";
      box.appendChild(it);
    });
  }


  /* ================= 任务下达与 R1 调度 ================= */
  function post(url, data){
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}) }).then(function(r){ return r.json(); });
  }
  /* 任务行操作：阻塞可重试；非执行中可删除（删除 = 台账四表 + 工作区文件 + 实时事件段） */
  function taskOps(t){
    var st = t.status || "";
    var ops = "";
    if (st === "阻塞") ops += "<button class='dretry' title='重试：重置为待派并重新触发执行链'>↻ 重试</button>";
    if (st !== "执行中") ops += "<button class='ddel' title='删除任务（含子任务 / 回报 / 工作区产物）'>删除</button>";
    return ops ? "<span class='dops'>" + ops + "</span>" : "";
  }
  function bindTaskOps(row, t){
    var btR = row.querySelector(".dretry");
    if (btR) btR.addEventListener("click", function(ev){
      ev.stopPropagation();
      btR.disabled = true; btR.textContent = "↻ 重试中…";
      api("/api/retry", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({no: t.no})}).then(function(j){
        if (!j || !j.ok){ btR.disabled = false; btR.textContent = "↻ 重试"; alert((j && j.msg) || "重试失败"); return; }
        btR.textContent = "✓ 已重置";
        loadQueue(); loadBoard(); liveStart();
        var st = $("dqState");
        if (st && j.msg){ st.className = "dq-state ok"; st.textContent = j.msg; }
      }).catch(function(){ btR.disabled = false; btR.textContent = "↻ 重试"; });
    });
    var btD = row.querySelector(".ddel");
    if (btD) btD.addEventListener("click", function(ev){
      ev.stopPropagation();
      if (!confirm("删除任务 " + t.no + "？将移除其子任务 / 回报 / 执行记录 / 工作区产物（不可恢复）。")) return;
      btD.disabled = true; btD.textContent = "删除中…";
      api("/api/task-delete", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({no: t.no})}).then(function(j){
        if (!j || !j.ok){ btD.disabled = false; btD.textContent = "删除"; alert((j && j.msg) || "删除失败"); return; }
        var st = $("dqState");
        if (st && j.msg){ st.className = "dq-state ok"; st.textContent = j.msg; }
        if (state.activeNo === t.no){ state.activeNo = null; showCurTask(null); }
        if (state.activeSub){ state.activeSub = null; }
        dropRunSec(t.no);
        loadQueue(); loadBoard(); renderAct(null); refreshSched(0);
      }).catch(function(){ btD.disabled = false; btD.textContent = "删除"; });
    });
  }

  /* 某任务的子任务完成情况（看板行数据已载入时给出 x/y；没数据返回 null） */
  function subStatsOf(taskNo){
    var total = 0, done = 0;
    (state.boardRows || []).forEach(function(x){
      if (x.taskNo !== taskNo) return;
      total++;
      if (boardColOf(x.st) === "完成") done++;
    });
    return total ? { done: done, total: total } : null;
  }
  function loadQueue(){
    api("/api/queue").then(function(j){
      if (!j || !j.ok) return;
      var box = $("dqQueue");
      box.innerHTML = "";
      (j.queue || []).forEach(function(t){
        taskTexts[t.no] = t.task || "";
        var row = document.createElement("div");
        var stKey = boardColOf(t.status);
        var stCls = stKey === "完成" ? "done" : stKey === "已派" ? "run" : stKey === "阻塞" ? "block" : "wait";
        row.className = "dq-row st-" + stCls + (t.status === "待派" ? " open" : "") + (t.status === "完成" ? " done" : "");
        row.title = t.no + "：" + t.task + "（点击查看任务输出：回报 / 派发 / 产物）";
        var sub = subStatsOf(t.no);
        var subTxt = sub ? "子任务 " + sub.done + "/" + sub.total + (sub.done === sub.total ? " ✓" : "") : "子任务 —";
        row.innerHTML = "<span class='dno'>" + esc(t.no) + "</span>"
          + "<span class='dstatus'>" + esc(t.status) + "</span>"
          + "<span class='dsub'>" + subTxt + "</span>"
          + taskOps(t);
        bindTaskOps(row, t);
        row.addEventListener("click", function(){ showTaskOutput(t.no, row); });
        box.appendChild(row);
      });
      if (!(j.queue || []).length){ box.innerHTML = "<div class='placeholder'>队列为空——在下方下达首个任务</div>"; }
    }).catch(function(){});
  }
  /* ===== 任务输出聚合：点击任务行查看回报/派发/产物 ===== */
  function fmtTs(ts){ return ts ? String(ts).replace("T", " ").slice(5, 16) : ""; }
  function showTaskOutput(no, row){
    state.activeNo = no;
    state.activeSub = null;
    showCurTask(no);
    renderAct(no);
    renderBoard();                    // 看板跟随选中任务筛选
    document.querySelectorAll(".dq-row").forEach(function(r){ r.classList.remove("sel"); });
    if (row) row.classList.add("sel");
    var box = $("taskOut");
    box.innerHTML = "<div class='placeholder'>加载任务 " + esc(no) + " 的输出…</div>";
    api("/api/task-output?no=" + encodeURIComponent(no)).then(function(j){
      if (!j || !j.ok){ box.innerHTML = "<div class='placeholder'>读取失败：" + esc(j && j.msg || "未知") + "</div>"; return; }
      var html = "<div class='to-head'>任务 " + esc(j.no) + " · 输出聚合</div>";
      /* 台账来自 SQLite（/api/task-output），这里只把结构化行拼成 md 表格用于渲染 */
      function mdRow(cells){ return "| " + cells.map(function(c){ return String(c == null ? "" : c).replace(/\|/g, "／").replace(/\n/g, " "); }).join(" | ") + " |"; }
      function mdTable(head, rows){ return renderMd(mdRow(head) + "\n|" + head.map(function(){ return "---"; }).join("|") + "|\n" + rows.join("\n")); }
      html += "<div class='to-sec'><b>执行历史</b>" + (j.executions && j.executions.length
        ? "<div class='exec-list'>" + j.executions.map(function(e){
            var done = !!e.result;
            var cls = !done ? "run" : (e.result === "完成" ? "ok" : (e.result === "部分" ? "warn" : "bad"));
            return "<div class='exec-row " + cls + "'>"
              + "<span class='ex-id'>" + esc(e.id) + "</span>"
              + "<span class='ex-role'>" + esc(e.role) + "</span>"
              + "<span class='ex-time'>" + esc(fmtTs(e.started_at)) + (e.ended_at ? " → " + esc(fmtTs(e.ended_at)) : " → 进行中") + "</span>"
              + "<em class='ex-st'>" + esc(e.result || "执行中") + "</em>"
              + (e.error ? "<div class='ex-err'>" + esc(e.error) + "</div>" : "")
              + "</div>";
          }).join("") + "</div>"
        : "<span class='empty'>尚无执行记录 —— 派发后产生，重试会追加新记录而非覆盖</span>") + "</div>";
      html += "<div class='to-sec'><b>回报</b>" + (j.reports && j.reports.length
        ? "<div class='to-rows'>" + mdTable(["日期", "子任务", "角色", "标题", "状态"], j.reports.map(function(x){
            return mdRow([x.date, x.sub_no, x.role, x.title, x.status]); })) + "</div>"
        : "<span class='empty'>暂无回报记录</span>") + "</div>";
      html += "<div class='to-sec'><b>子任务</b>" + (j.plan && j.plan.length
        ? "<div class='to-rows'>" + mdTable(["编号", "子任务", "角色", "期望产出", "状态"], j.plan.map(function(x){
            return mdRow([x.no, x.sub, x.role, x.expect, x.st]); })) + "</div>"
        : "<span class='empty'>暂无子任务记录</span>") + "</div>";
      html += "<div class='to-sec'><b>角色产物（点击查看全文）</b>";
      if (j.files && j.files.length){
        html += "<div class='to-caps'>";
        j.files.forEach(function(f){
          html += "<span class='to-cap' data-rel='" + esc(f.rel) + "' title='" + esc(f.rel) + "'>" + esc(f.name) + "</span>";
        });
        html += "</div>";
      } else { html += "<span class='empty'>暂无包含该编号的产出文件</span>"; }
      html += "</div>";
      if (j.log){ html += "<div class='to-sec'><b>调度日志片段</b><pre>" + esc(j.log) + "</pre></div>"; }
      box.innerHTML = html;
      box.querySelectorAll(".to-cap").forEach(function(f){
        f.addEventListener("click", function(){
          var rel = f.getAttribute("data-rel");
          box.innerHTML = "<div class='placeholder'>加载 " + esc(rel) + " 全文…</div>";
          api("/api/md?rel=" + encodeURIComponent(rel)).then(function(r){
            if (r && r.ok){
              box.innerHTML = "<div class='to-head'><a href='javascript:void(0)' id='toBack'>← 返回任务输出</a> <span>" + esc(rel.split("/").pop()) + "</span></div>"
                + "<div class='markdown-body to-doc'>" + renderMd(r.text || "") + "</div>";
              var bk = box.querySelector("#toBack");
              if (bk) bk.addEventListener("click", function(){ showTaskOutput(no, null); });
            } else { box.innerHTML = "<div class='placeholder'>读取失败：" + esc(r && r.msg || "未知") + "</div>"; }
          }).catch(function(e){ box.innerHTML = "<div class='placeholder'>异常：" + esc(e.message) + "</div>"; });
        });
      });
    }).catch(function(e){ box.innerHTML = "<div class='placeholder'>异常：" + esc(e.message) + "</div>"; });
  }
  /* ===== 子任务内容：点击看板卡片查看该子任务自己的产出全文（不跳到任务聚合） ===== */
  function showSubOutput(x){
    state.activeNo = x.taskNo;
    state.activeSub = x.no;
    showCurTask(x.taskNo);
    renderAct(x.taskNo);
    renderBoard();
    var box = $("taskOut");
    box.innerHTML = "<div class='placeholder'>加载子任务 " + esc(x.no) + " …</div>";
    api("/api/sub-output?no=" + encodeURIComponent(x.no)).then(function(j){
      if (!j || !j.ok){ box.innerHTML = "<div class='placeholder'>子任务产出读取失败：" + esc(j && j.msg || "未知") + "</div>"; return; }
      var m = j.meta || {};
      var nm = m.roleName || roleName(m.role) || x.role || "";
      var hh = "<div class='to-head'><a href='javascript:void(0)' id='subBack'>← 返回任务 " + esc(x.taskNo) + " 聚合</a>"
        + " <span class='sub-no'>" + esc(x.no) + "</span><b>" + esc(nm) + "</b><em>" + esc(m.status || x.st || "") + "</em></div>";
      var sub = String(m.sub || x.sub || "");
      var exp = String(m.expect || x.expect || "");
      if (sub){ hh += "<div class='sub-line'>子任务：" + esc(sub) + "</div>"; }
      if (exp){ hh += "<div class='sub-line sub-expect'>期望产出：" + esc(exp) + "</div>"; }
      box.innerHTML = hh + "<div class='markdown-body to-doc'>" + renderMd(j.text || "") + "</div>";
      var bk = box.querySelector("#subBack");
      if (bk) bk.addEventListener("click", function(){ showTaskOutput(x.taskNo, null); });
    }).catch(function(e){ box.innerHTML = "<div class='placeholder'>异常：" + esc(e.message) + "</div>"; });
  }

  /* ===== R1 派发（合并原「运行调度 + 落地产出」两步为链式） ===== */
  /* ===== 调度暂停/继续（单按钮 toggle；恢复时自动续跑剩余派发） ===== */
  function toggleSched(){
    var st = $("dqState");
    api("/api/scheduler").then(function(j){
      var paused = !!(j && j.ok && (j.state || {}).paused);
      var action = paused ? "resume" : "pause";
      st.textContent = paused ? "恢复执行中…" : "暂停中…";
      post("/api/plan-pause", { action: action }).then(function(r){
        if (r && r.ok){
          if (paused){ st.className = "dq-state"; st.textContent = "已恢复 —— 继续按派发单执行"; planExec(); }
          else { st.className = "dq-state paused"; st.textContent = "已暂停：当前行完成后停止，点击按钮继续"; refreshSched(0); }
        } else { st.className = "dq-state"; st.textContent = "操作失败：" + (r && r.msg || "未知"); }
      }).catch(function(e){ st.textContent = "异常：" + e.message; });
    }).catch(function(){});
  }

  function refreshSched(show){
    /* 调度引擎状态（空闲/调度中/暂停）统一显示在下方状态带 #dqState（schedStat 已并入移除）。 */
    api("/api/scheduler").then(function(j){
      var st = $("dqState");
      if (!j || !j.ok){ if (st) st.textContent = "调度状态未知"; return; }
      var s = j.state || {};
      var txt = s.busy ? "调度中：" + (s.tag || "") + "（后台执行中）"
        : "调度空闲" + (s.lastOk === true ? " ✓ 上轮完成" : s.lastOk === false ? " ✗ 上轮失败" : "");
      if (st){ st.className = "dq-state" + (s.busy ? " busy" : "") + (s.paused ? " paused" : ""); st.textContent = (s.paused ? "⏸ " : "") + txt; }
      var bt = $("btnToggleSched");
      if (bt){ bt.innerHTML = s.paused ? "▶ 恢复" : "⏸ 暂停"; bt.title = s.paused ? "恢复自动执行链" : "暂停自动执行链"; }
      if (show){ loadQueue() }
    }).catch(function(){});
  }

  /* ===== 一键下达：R1 自动拆解派发（单按钮 + 全自动轮询反馈） ===== */
  function oneClickDispatch(){
    var v = $("dqInput").value.trim();
    var stj = $("dqState");
    if (!v){ if (stj) stj.textContent = "请先填写任务内容"; return; }
    var ex = ($("dqExpect") && $("dqExpect").value.trim()) || "R1 判断";
    if (stj){ stj.className = "dq-state busy"; stj.textContent = "下达中…"; }
    post("/api/dispatch", { task: v, expect: ex }).then(function(j){
      if (!j || !j.ok){ if (stj){ stj.className = "dq-state"; stj.textContent = "下达失败：" + (j && j.msg || "未知"); } return; }
      $("dqInput").value = "";
      if (stj){ stj.className = "dq-state busy"; stj.innerHTML = "已下达 <b>" + esc(j.no) + "</b> —— 全自动流水线：R1 拆解 → subagent 派发各角色 → 回报落库"; }
      loadQueue();
      loadBoard();
      pollAuto(j.no);
      liveStart();
    }).catch(function(e){ if (stj) stj.textContent = "下达异常：" + e.message; });
  }
  function pollAuto(no){
    var n2 = 0, seen = { st: "" };
    var timer = setInterval(function(){
      n2++;
      api("/api/queue").then(function(jq){
        var row = (jq.queue || []).filter(function(t){ return t.no === no; })[0];
        var stj = $("dqState");
        if (row && stj){
          var st = row.status || "";
          var rep = row.report && row.report !== "—" ? String(row.report) : "";
          if (rep){ stj.className = "dq-state ok"; stj.innerHTML = "<b>" + esc(no) + "</b> ✓ " + st + " · 回报：" + esc(rep.slice(0, 80)); }
          else if (st !== seen.st && st){ seen.st = st; stj.className = "dq-state busy"; stj.innerHTML = "<b>" + esc(no) + "</b> · " + st + "（R1 拆解派发中，主会话开着即自动承接）"; }
        }
        loadQueue();
        if (row && row.report && row.report !== "—" && n2 >= 2){ clearInterval(timer); }
        else if (n2 >= 160){ clearInterval(timer); }
      }).catch(function(){});
    }, 2500);
  }

  function planExec(){
    var pe = $("dqState");
    if (pe){ pe.className = "dq-state"; pe.textContent = "按派发单启动子任务…"; }
    post("/api/plan-execute").then(function(j){
      if (pe){ pe.className = "dq-state" + (j && j.ok ? " ok" : ""); pe.textContent = j && j.ok ? ("派发指令已生成：" + ((j.result || {}).issued || []).join(", ")) : ("启动失败：" + (j && j.msg || "未知")); }
    }).catch(function(e){ if (pe){ pe.className = "dq-state"; pe.textContent = "异常：" + e.message; } });
  }
  var dqTicking = false;
  function dqTick(){
    if (dqTicking) return; dqTicking = true;
    var sc = $("dqState");
    if (sc && sc.className.indexOf("busy") >= 0){ loadQueue() }
    refreshSched(0);
    setTimeout(function(){ dqTicking = false; }, 4000);
  }
  document.getElementById("btnOneClick").addEventListener("click", oneClickDispatch);
  var bt = document.getElementById("btnToggleSched");
  if (bt) bt.addEventListener("click", toggleSched);
  setInterval(dqTick, 12000);
  /* ================= 批阅台 ================= */
  function loadPiyue(){
    state.projText = null;   // 项目整体进展缓存随批阅台重进而刷新
    api("/api/pending").then(function(j){
      if (!j || !j.ok){ $("pendingList").innerHTML = "<div class='placeholder'>加载失败：" + esc(j && j.msg || "未知错误") + "</div>"; return; }
      state.pending = j.pending || [];
      state.work = j.work || [];
      state.archive = j.archive || [];
      renderList();
      api("/api/summary").then(refreshStats).catch(function(){});
    }).catch(function(e){
      $("pendingList").innerHTML = "<div class='placeholder'>后端未连接：" + esc(e.message) + "</div>";
    });
  }

  function renderList(){
    var cntW = $("workCount"); if (cntW) cntW.textContent = "（" + state.work.length + "）";
    var cntP = $("pendingCount"); if (cntP) cntP.textContent = "（" + state.pending.length + "）";
    function card(it, kind){
      var d = document.createElement("div");
      if (kind === "work"){
        // 工作内容卡片：紧凑 —— #编号(小) + 任务号 + 是否已阅
        d.className = "p-card work compact";
        d.dataset.kind = "work";
        d.dataset.n = it.n;
        d.title = it.title;
        var mm = /任务\s+(T-\d+)/.exec(it.title || "");
        var tno = mm ? mm[1] : String(it.title || "").slice(0, 16);
        d.innerHTML = "<span class='num'>#" + it.n + "</span><span class='name'>" + esc(tno) + "</span>"
          + "<span class='wst'>○ 未阅</span>";
        d.addEventListener("click", function(){ showDetail(it, "work"); });
        return d;
      }
      d.className = "p-card";
      d.dataset.kind = "pending";
      d.dataset.n = it.n;
      var prev = "";
      (it.lines || []).forEach(function(ln){
        if (ln.indexOf("背景") >= 0 || ln.indexOf("需要 R0 拍板") >= 0){ prev += ln.split("：").pop() + " "; }
      });
      d.innerHTML = "<span class='num'>#" + it.n + "</span><span class='name'>" + esc(it.title) + "</span>"
        + (prev ? "<div class='preview'>" + esc(prev.trim().slice(0, 140)) + "</div>" : "");
      d.addEventListener("click", function(){ showDetail(it, "pending"); });
      return d;
    }
    var wb = $("workList");
    wb.innerHTML = "";
    if (!state.work.length){ wb.innerHTML = "<div class='placeholder'>暂无工作进展 —— 任务执行完成后自动呈报到这里</div>"; }
    state.work.forEach(function(it){ wb.appendChild(card(it, "work")); });
    var pb = $("pendingList");
    pb.innerHTML = "";
    if (!state.pending.length){ pb.innerHTML = "<div class='placeholder'>当前无待裁决 —— R1 认为需拍板时才呈报</div>"; }
    state.pending.forEach(function(it){ pb.appendChild(card(it, "pending")); });
    var ar = $("archiveList");
    ar.innerHTML = "";
    (state.archive || []).forEach(function(it){
      var a = document.createElement("div");
      var aKind = it.kind === "待决" ? "dec" : "work";
      a.className = "a-item a-" + aKind;
      a.dataset.kind = aKind;
      a.title = "点击查看已批阅原文（只读）";
      a.innerHTML = "<span class='a-ico'>" + (aKind === "dec" ? "决策" : "工作") + "</span>"
        + "<span class='n'>#" + it.n + "</span><span class='t'>" + esc(it.title) + "</span>";
      a.addEventListener("click", function(){ showDetail(it, "archive"); });
      ar.appendChild(a);
    });
    if (state.pending.length){ showDetail(state.pending[0], "pending"); }
    else if (state.work.length){ showDetail(state.work[0], "work"); }
    else { showDetail(null, "pending"); }
  }

  /* 决策项只读一条“项目整体进展”（不是某任务 x/y 完成），取自队列 + 看板 + 台账汇总 */
  function loadProjText(cb){
    if (state.projText){ if (cb) cb(state.projText); return; }
    var err = function(){ state.projText = "项目进展读取失败"; if (cb) cb(state.projText); };
    api("/api/queue").then(function(jq){
      api("/api/plan-rows").then(function(jp){
        api("/api/summary").then(function(js){
          var tq = (jq && jq.queue) || [], sp = (jp && jp.rows) || [];
          var tk = { n: tq.length, ok: 0, run: 0, block: 0 };
          tq.forEach(function(x){
            var s = String(x.status || "");
            if (s.indexOf("完成") >= 0 || s.indexOf("部分") >= 0) tk.ok++;
            else if (s.indexOf("阻塞") >= 0) tk.block++;
            else if (s.indexOf("执行") >= 0 || s.indexOf("已派") >= 0) tk.run++;
          });
          var bk = { done: 0, run: 0, wait: 0, block: 0 };
          sp.forEach(function(x){
            var c = boardColOf(x.st);
            if (c === "完成") bk.done++; else if (c === "已派") bk.run++;
            else if (c === "阻塞") bk.block++; else bk.wait++;
          });
          var parts = [];
          if (tk.n) parts.push("任务 " + tk.ok + "/" + tk.n + " 完成" + (tk.block ? "（阻塞 " + tk.block + "）" : ""));
          if (sp.length) parts.push("子任务 " + bk.done + "/" + sp.length + " 完成" + (bk.block ? "（阻塞 " + bk.block + "）" : ""));
          if (js){
            if (js.pendingCount) parts.push("决策待裁决 " + js.pendingCount + " 条");
            if (js.workCount) parts.push("例行进展 " + js.workCount + " 条待阅");
          }
          var t = parts.join(" · ") || "暂无任务与子任务 —— 项目尚未开工";
          state.projText = t; if (cb) cb(t);
        }).catch(err);
      }).catch(err);
    }).catch(err);
  }

  /* 批阅条目行解析：以 - **字段**：值 开头的行为字段表，其余行归为自由段落 */
  function splitPiyueLines(lines){
    var flds = {}, paras = [];
    (lines || []).forEach(function(ln){
      var m = /^-\s*\*\*([^*]+?)\*\*\s*[:：]\s*([\s\S]*)$/.exec(ln);
      if (m){ var k = m[1].trim(); flds[k] = (k in flds ? flds[k] + "\n" : "") + (m[2] || "").trim(); return; }
      if (String(ln).trim()) paras.push(ln);
    });
    return { flds: flds, paras: paras };
  }
  /* 决策归档：按任务队列实时回填 R1 执行状态 */
  function bindDecExec(no){
    api("/api/queue").then(function(j){
      var t = ((j && j.queue) || []).filter(function(x){ return x.no === no; })[0];
      var el = $("decExec");
      if (!el) return;
      if (!t){ el.textContent = "任务 " + no + " 不在任务队列（R1 尚未建任务或已被删除）"; return; }
      var st = t.status || "";
      var txt;
      if (st.indexOf("完成") >= 0 || st.indexOf("部分") >= 0) txt = "✓ 已执行 · " + no + "（" + st + "）";
      else if (st.indexOf("阻塞") >= 0) txt = "未完成 · " + no + "（阻塞，可到工作台重试）";
      else txt = "执行中 · " + no + "（" + st + "）";
      el.textContent = txt;
    }).catch(function(){});
  }

  function showDetail(it, kind){
    kind = kind || "pending";
    state.cur = it;
    document.querySelectorAll(".p-card").forEach(function(c){ c.classList.remove("active"); });
    document.querySelectorAll(".a-item").forEach(function(c){ c.classList.remove("active"); });
    if (it){
      document.querySelectorAll(".p-card").forEach(function(c){
        if (c.dataset && c.dataset.n === String(it.n) && (kind === "archive" || c.dataset.kind === kind)){ c.classList.add("active"); }
      });
      if (kind === "archive"){
        document.querySelectorAll(".a-item").forEach(function(c){
          var nm = c.querySelector(".n");
          if (nm && nm.textContent.indexOf("#" + it.n) >= 0){ c.classList.add("active"); }
        });
      }
    }
    var d = $("pendingDetail");
    if (!it){ d.innerHTML = "<div class='placeholder'>← 从左侧选择 工作内容 或 决策裁决 查看</div>"; $("piyueForm").hidden = true; return; }
    var pre = kind === "work" ? "工作 #" : (kind === "archive" ? "已批阅 #" : "待决 #");
    /* 决策裁决的归档：只看 决策内容 / R0 决策 / R1 是否执行 —— 不展示工作产物 */
    if (kind === "archive" && (it.kind === "待决" || it.kind === "dec")){
      d.className = "dossier pending-lean";
      var rd = splitPiyueLines(it.lines);
      function pickA(sub){ for (var k in rd.flds){ if (k.indexOf(sub) >= 0) return rd.flds[k]; } return ""; }
      var askA = pickA("拍板") || pickA("决策") || rd.paras.join("\n") || "";
      var judgeA = (rd.flds["R0 批阅"] || "").trim();
      var execA = (rd.flds["R1 执行"] || "").trim();
      var verbA = judgeA.indexOf("驳回") >= 0 ? "驳回" : (judgeA.indexOf("批准") >= 0 || judgeA.indexOf("同意") >= 0 ? "批准" : "修改");
      var secA = function(t, inner){ return "<div class='doc-sec'><div class='doc-sec-head'>" + esc(t) + "</div>" + inner + "</div>"; };
      var hA = "<div class='piyue-head'><h1><span class='n'>决策 #" + it.n + "</span> " + esc(it.title) + "</h1><div class='piyue-head-ops'><span class='arch-badge dec'>✓ 决策已批</span></div></div>";
      hA += secA("决策内容", askA ? "<div class='markdown-body to-doc'>" + renderMd(askA) + "</div>" : "<span class='empty'>（原文未写明内容）</span>");
      var vCls = verbA === "批准" ? "v-ok" : (verbA === "驳回" ? "v-rej" : "v-mod");
      hA += secA("R0 决策", "<div class='verdict " + vCls + "'><b>" + verbA + "</b><span>" + esc(judgeA || "（无批语）") + "</span></div>");
      var mT = /(T-\d+)/.exec(execA || "");
      var initExec = verbA === "批准"
        ? (execA ? execA + "（实时核对任务状态…）" : "已批阅，等待 R1 建任务执行")
        : "未采纳（" + verbA + "）—— 无需建任务执行";
      hA += secA("R1 是否执行", "<div class='dec-exec' id='decExec'>" + esc(initExec) + "</div>");
      d.innerHTML = hA;
      if (verbA === "批准" && mT){ bindDecExec(mT[1]); }
      $("piyueForm").hidden = true;
      $("opinionInput").value = "";
      $("piyueStatus").textContent = "";
      return;
    }
    if (kind === "pending"){
      /* 决策项精简版：只要 项目整体进展 + 待决内容全文 + R1 建议；不再铺开逐字段与角色产物 */
      var h0 = "<h1><span class='n'>" + pre + it.n + "</span> " + esc(it.title) + "</h1>";
      d.className = "dossier pending-lean";
      var _rp = splitPiyueLines(it.lines);
      var flds = _rp.flds, paras = _rp.paras;
      function pick(sub){ for (var k in flds){ if (k.indexOf(sub) >= 0) return flds[k]; } return ""; }
      /* 机制套话（“任务含决策信号…请 R0 裁决；驳回将触发重新派发”）不是具体待决内容，
         检测到就不当“需要决策什么”展示，避免 R0 看到读不出问题的空话 */
      function blankAsk(t){
        return !t || /决策信号|请 ?R0 ?裁决|R0 裁决|驳回|重新派发|修改意见|回报未列出|请展开|请直接批复|读完完整产出/.test(String(t));
      }
      var taskTxt = ("任务" in flds) ? flds["任务"] : "";
      var askRaw = pick("拍板") || pick("决策") || paras.join("\n") || "";
      var ask = blankAsk(askRaw) ? "" : askRaw;
      var adv = pick("建议");
      function sec(title, md){
        return "<div class='doc-sec'><div class='doc-sec-head'>" + esc(title) + "</div>"
          + "<div class='sec-body markdown-body to-doc'>" + renderMd(md || "") + "</div></div>";
      }
      /* 当“需要拍板什么”就是任务原话（回报没另写）时不重复展示 dec-sub */
      if (taskTxt && (!ask || ask.indexOf(taskTxt) !== 0)){ h0 += "<div class='dec-sub'>任务：" + esc(taskTxt) + "</div>"; }
      h0 += "<div class='doc-sec'><div class='doc-sec-head'>项目当前进展</div><div id='projProg' class='proj-line'>计算中…</div></div>";
      if (ask){
        h0 += sec("需要决策什么", ask);
      } else {
        h0 += "<div class='doc-sec'><div class='doc-sec-head'>需要决策什么</div>"
          + "<div class='noask'>这条回报只标了「需拍板」却没写出具体要拍板的内容（只写了机制说明，读不出问题）。"
          + "请直接 <b>驳回 / 修改</b> 让执行角色补写「现状背景 → 可选方案 → 建议」；或在下框批注里按你的判断给出裁决。</div></div>";
      }
      if (adv){ h0 += sec("R1 的建议", adv); }
      d.innerHTML = h0;
      var pp = $("projProg");
      if (pp){ loadProjText(function(t){ if (pp.isConnected) pp.textContent = t; }); }
      $("piyueForm").hidden = false;
      $("opinionInput").value = "";
      $("piyueStatus").textContent = "";
      $("piyueStatus").className = "form-status";
      return;
    }
    var sumRel = null;
    (it.lines || []).forEach(function(ln){
      var i3 = ln.indexOf("**汇总文件**");
      if (i3 >= 0){ sumRel = ln.slice(ln.indexOf("：", i3) + 1).trim(); }
    });
    var taskNo = null;
    var mmT = /任务[ ]+(T-[0-9A-Za-z-]+)/.exec(it.title || "");
    if (mmT) taskNo = mmT[1];
    var h = "<div class='piyue-head'><h1><span class='n'>" + pre + it.n + "</span> " + esc(it.title) + "</h1><div class='piyue-head-ops'>";
    if (kind === "archive"){ h += "<span class='arch-badge'>✓ 已阅归档</span>"; }
    if (kind === "work"){ h += "<button id='btnWorkArchive' class='mini'>已阅归档</button><span id='workMsg' class='form-status'></span>"; }
    h += "</div></div>";
    // 任务信息（概要字段，始终可见）
    var extraHtml = "";
    (it.lines || []).forEach(function(ln){
      if (ln.indexOf("- **") === 0 && ln.indexOf("：") > 0){
        var idx = ln.indexOf("**：", 4);
        var key = idx > 0 ? ln.slice(4, idx) : ln;
        var val = idx > 0 ? ln.slice(idx + 3) : "";
        if (key === "汇总文件") return;
        if (val.indexOf("**") >= 0 || val.indexOf("# ") >= 0 || val.length > 90){
          extraHtml += "<div class='fld'><b>" + esc(key) + "</b><div class='fld-md markdown-body'>" + renderMd(val) + "</div></div>";
        } else {
          extraHtml += "<div class='fld'><b>" + esc(key) + "</b><span>" + esc(val) + "</span></div>";
        }
      }
    });
    if (extraHtml){ h += "<div class='doc-sec'><div class='doc-sec-head'>任务信息</div>" + extraHtml + "</div>"; }
    // R1 汇总报告：折叠按钮，点击在其正下方展开（默认收起）
    h += "<div class='doc-sec'><button type='button' class='sec-btn' id='btnSum'><span class='arr'>▸</span> R1 汇总报告" + (taskNo ? " <em>任务 " + esc(taskNo) + "</em>" : "") + (sumRel ? "" : "（无汇总文件）") + "</button>";
    h += "<div id='sumBody' class='sec-body markdown-body to-doc' style='display:none'></div></div>";
    // 执行角色产物：名称列表，点击名称在其正下方展开
    h += "<div class='doc-sec'><div class='doc-sec-head'>执行角色产物</div>";
    h += "<div id='prodList' class='prod-list'>" + (taskNo ? "<div class='placeholder'>加载产物清单…</div>" : "<div class='placeholder'>暂无产物文件</div>") + "</div></div>";
    d.className = "dossier";
    d.innerHTML = h;
    $("piyueForm").hidden = true;
    $("opinionInput").value = "";
    $("piyueStatus").textContent = "";
    $("piyueStatus").className = "form-status";
    if (kind === "work"){
      document.querySelectorAll(".p-card.compact").forEach(function(c){
        var w = c.querySelector(".wst");
        if (w && c.dataset && c.dataset.n === String(it.n)){ w.textContent = "✓ 已阅"; w.classList.add("seen"); }
      });
    }
    // 通用：载入 md 到容器
    function loadInto(box, rel, label){
      box.innerHTML = "<div class='placeholder'>加载 " + esc(label || "") + "…</div>";
      api("/api/md?rel=" + encodeURIComponent(rel)).then(function(j){
        if (j && j.ok){ box.innerHTML = renderMd(j.text || ""); }
        else { box.innerHTML = "<div class='placeholder'>加载失败：" + esc(j && j.msg || "未知") + "</div>"; }
      }).catch(function(e){ box.innerHTML = "<div class='placeholder'>加载异常：" + esc(e.message) + "</div>"; });
    }
    // 执行角色产物折叠列表：点击行展开该文件全文（工作/待决条目的“完整上下文”）
    function bindTaskFiles(listId, taskNo){
      var pl = document.getElementById(listId);
      if (!pl || !taskNo) return;
      api("/api/task-output?no=" + encodeURIComponent(taskNo)).then(function(j){
        if (!j || !j.ok){ pl.innerHTML = "<div class='placeholder'>产物清单加载失败</div>"; return; }
        var rows = (j.files || []).filter(function(f){ return /\.md$/.test(f.rel || "") && f.rel.indexOf("-工作汇总") < 0 && f.rel.indexOf("-summary.md") < 0; })
          .map(function(f){ var seg = String(f.rel || "").split("/"); return { role: seg.length > 1 ? seg[1] : "", name: f.name, rel: f.rel }; });
        if (!rows.length){ pl.innerHTML = "<div class='placeholder'>暂无产物文件</div>"; return; }
        pl.innerHTML = "";
        var loaded = {};
        rows.forEach(function(x){
          var wrap = document.createElement("div");
          wrap.className = "prod-wrap";
          var it2 = document.createElement("div");
          it2.className = "prod-item";
          it2.innerHTML = "<span class='arr'>▸</span><span class='pi'>" + esc(x.role) + "</span><em>" + esc(x.name) + "</em>";
          var body = document.createElement("div");
          body.className = "sec-body markdown-body to-doc";
          body.style.display = "none";
          it2.addEventListener("click", function(){
            if (body.style.display === "none"){
              body.style.display = "";
              it2.querySelector(".arr").textContent = "▾";
              if (!loaded[x.rel]){ loaded[x.rel] = true; loadInto(body, x.rel, x.name); }
            } else {
              body.style.display = "none";
              it2.querySelector(".arr").textContent = "▸";
            }
          });
          wrap.appendChild(it2);
          wrap.appendChild(body);
          pl.appendChild(wrap);
        });
      }).catch(function(){ pl.innerHTML = "<div class='placeholder'>加载异常</div>"; });
    }
    // R1 汇总折叠
    var btnSum = $("btnSum");
    var sumBody = $("sumBody");
    var sumLoaded = false;
    if (btnSum && sumRel && sumBody){
      btnSum.addEventListener("click", function(){
        if (sumBody.style.display === "none"){
          sumBody.style.display = "";
          btnSum.querySelector(".arr").textContent = "▾";
          if (!sumLoaded){ sumLoaded = true; loadInto(sumBody, sumRel, "R1 汇总"); }
        } else {
          sumBody.style.display = "none";
          btnSum.querySelector(".arr").textContent = "▸";
        }
      });
    } else if (btnSum){ btnSum.disabled = true; }
    // 归档按钮
    var ba = $("btnWorkArchive");
    if (ba) ba.addEventListener("click", function(){
      api("/api/work-archive", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item: it.n }) }).then(function(j){
        var m = $("workMsg");
        if (!j || !j.ok){ if (m){ m.className = "form-status err"; m.textContent = "归档失败：" + esc(j && j.msg || "未知"); } return; }
        if (m){ m.className = "form-status ok"; m.textContent = "已归档 ✓"; }
        loadPiyue();
      }).catch(function(e){ var m = $("workMsg"); if (m){ m.className = "form-status err"; m.textContent = "异常：" + e.message; } });
    });
    // 产物列表：每项点击在其正下方展开/收起（完整上下文）
    bindTaskFiles("prodList", taskNo);
  }
  function submitPiyue(judge){
    var it = state.cur;
    if (!it) return;
    var op = $("opinionInput").value.trim();
    var st = $("piyueStatus");
    st.textContent = "提交中…";
    api("/api/piyue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item: it.n, judge: judge, opinion: op })
    }).then(function(j){
      if (j && j.ok){
        st.className = "form-status ok";
        st.textContent = "已盖章：《决策/批阅台.md》待决 #" + it.n + " → " + judge;
        setTimeout(function(){ st.textContent = ""; }, 4000);
        loadPiyue();
      } else {
        st.className = "form-status err";
        st.textContent = "写入失败：" + esc(j && j.msg || "未知错误");
      }
    }).catch(function(e){
      st.className = "form-status err";
      st.textContent = "提交异常：" + esc(e.message);
    });
  }

  document.querySelectorAll(".seal").forEach(function(b){
    b.addEventListener("click", function(){ submitPiyue(this.getAttribute("data-judge")); });
  });

  /* ================= 知识库（档案卡片：R1 管理 · 全体角色共同维护） ================= */
  function loadKbEntries(){
    var g = $("kbGrid");
    if (!g) return;
    g.innerHTML = "<div class='placeholder'>加载中…</div>";
    api("/api/kb-entries").then(function(j){
      if (!j || !j.ok){ g.innerHTML = "<div class='placeholder'>加载失败：" + esc(j && j.msg || "") + "</div>"; return; }
      g.innerHTML = "";
      var lastTop = null;
      (j.entries || []).forEach(function(e){
        // 知识库根直接平铺：根目录本身的分组头已去掉（占位组）；仅真实子目录才渲染 kb-group
        var t2 = (e.top && e.top !== "[根]") ? e.top : "";
        if (t2 && t2 !== lastTop){ var gh = document.createElement("div"); gh.className = "kb-group"; gh.textContent = "▸ " + t2; g.appendChild(gh); }
        lastTop = t2;
        var c = document.createElement("div");
        c.className = "kb-card";
        var ic = t2 ? "▸" : "▪";
        var mt = "";
        try { mt = new Date((e.mtime || 0) * 1000).toLocaleDateString(); } catch (err) {}
        c.innerHTML = "<div class='kb-card-head'><span class='kb-ico'>" + ic + "</span><b>" + esc(e.name) + "</b><em>" + mt + "</em></div>" +
          "<div class='kb-card-sum'>" + esc(e.head) + "</div>" +
          "<div class='kb-card-meta'>维护：R1（老板助理）归档 · " + esc(e.rel) + "</div>";
        c.addEventListener("click", function(){ showKbDoc(e.rel, e.name, mt); });
        g.appendChild(c);
      });
      if (!(j.entries || []).length){ g.innerHTML = "<div class='placeholder'>知识库暂无档案 —— 各角色产出经 R1 审核归档后自动出现在这里（见《知识库索引》沉淀建议）</div>"; }
    }).catch(function(e2){ g.innerHTML = "<div class='placeholder'>异常：" + esc(e2.message) + "</div>"; });
  }

  function showKbDoc(rel, name, dt){
    var g = $("kbGrid"), d = $("kbDoc");
    if (!g || !d) return;
    g.style.display = "none"; d.style.display = "";
    d.innerHTML = "<div class='back-bar'><a href='javascript:void(0)' id='kbBack'>← 返回档案列表</a></div>" +
      "<div class='file-title'>" + esc(name) + " ｜ 知识库档案 · 管理员 老板助理（枢纽）R1 · 更新 " + esc(dt || "") + "</div>" +
      "<div class='markdown-body'><div class='placeholder'>加载中…</div></div>";
    api("/api/md?rel=" + encodeURIComponent(rel)).then(function(j){
      var b = d.querySelector(".markdown-body");
      if (b) b.innerHTML = (j && j.ok) ? renderMd(j.text || "") : "<div class='placeholder'>" + esc(j && j.msg || "读取失败") + "</div>";
    }).catch(function(e){ var b = d.querySelector(".markdown-body"); if (b) b.innerHTML = "<div class='placeholder'>" + esc(e.message) + "</div>"; });
    var bk = d.querySelector("#kbBack");
    if (bk) bk.addEventListener("click", function(){ g.style.display = ""; d.style.display = "none"; });
  }

  /* ================= 执行监控（agent 遥测：完整 prompt + 流式输出 + 工具调用） ================= */
  /* ================= 实时事件流（自动执行链阶段事件 → 详情面板底部） ================= */
  function liveStart(){
    if (state.runTimer) return;
    state.runTimer = setInterval(runTick, 1400);
    runTick();
  }
  function liveStop(){
    if (state.runTimer){ clearInterval(state.runTimer); state.runTimer = null; }
  }

  /* ================= 子任务看板 =================
     列 = opc-web 现有状态语义；「部分」并入完成列并打角标（单独一列常年空着）。 */
  var BOARD_COLS = [
    { key: "待派", cls: "wait" },
    { key: "已派", cls: "run" },
    { key: "完成", cls: "done" },
    { key: "阻塞", cls: "block" }
  ];
  function boardColOf(st){
    var s = String(st || "待派");
    if (s.indexOf("阻塞") >= 0) return "阻塞";
    if (s.indexOf("完成") >= 0 || s.indexOf("部分") >= 0) return "完成";
    if (s.indexOf("已派") >= 0 || s.indexOf("执行") >= 0) return "已派";
    return "待派";
  }
  function loadBoard(){
    api("/api/plan-rows").then(function(j){
      if (!j || !j.ok) return;
      state.boardRows = j.rows || [];
      renderBoard();
      loadQueue();   // 任务行上的“子任务 x/y”随看板数据刷新
    }).catch(function(){});
  }
  function renderBoard(){
    var box = $("board");
    if (!box) return;
    var rows = state.boardRows || [];
    if (state.activeNo) rows = rows.filter(function(x){ return x.taskNo === state.activeNo; });
    var q = (($("boardSearch") || {}).value || "").trim().toLowerCase();
    if (q) rows = rows.filter(function(x){
      return (x.no + " " + x.sub + " " + x.role + " " + roleName(x.role)).toLowerCase().indexOf(q) >= 0;
    });
    var stat = $("boardStat");
    if (stat) stat.textContent = rows.length + " 个子任务"
      + (state.activeNo ? " · " + state.activeNo : "") + (q ? " · 已筛选" : "");
    if (!rows.length){
      box.innerHTML = "<div class='placeholder'>" + (q || state.activeNo ? "没有匹配的子任务" : "暂无子任务 —— 下达任务后 R1 拆解即出现") + "</div>";
      return;
    }
    var buckets = {};
    BOARD_COLS.forEach(function(c){ buckets[c.key] = []; });
    rows.forEach(function(x){ buckets[boardColOf(x.st)].push(x); });
    /* 未点任务且未搜索 = 全局总览：每列倒序（最新在前），最多显示 5 张卡，其余收进 +N 提示 */
    if (!state.activeNo && !q){
      BOARD_COLS.forEach(function(c){
        var arr = buckets[c.key];
        arr.reverse();
        if (arr.length > 5){ arr.more = arr.length - 5; arr.length = 5; }
      });
    }
    box.innerHTML = "";
    BOARD_COLS.forEach(function(c){
      var col = document.createElement("div");
      col.className = "bd-col " + c.cls;
      var head = document.createElement("div");
      head.className = "bd-head";
      var moreN = buckets[c.key].more || 0;
      head.innerHTML = "<span>" + esc(c.key) + "</span><em>" + buckets[c.key].length + (moreN ? "+" + moreN : "") + "</em>";
      col.appendChild(head);
      var list = document.createElement("div");
      list.className = "bd-list";
      buckets[c.key].forEach(function(x){ list.appendChild(boardCard(x)); });
      if (!buckets[c.key].length){
        var e0 = document.createElement("div");
        e0.className = "bd-empty";
        e0.textContent = "—";
        list.appendChild(e0);
      } else if (moreN){
        var m2 = document.createElement("div");
        m2.className = "bd-more";
        m2.textContent = "… 更早还有 " + moreN + " 条 · 点任务看全部";
        list.appendChild(m2);
      }
      col.appendChild(list);
      box.appendChild(col);
    });
  }
  function boardCard(x){
    var el = document.createElement("div");
    el.className = "bd-card" + (state.activeSub === x.no ? " sel" : "");
    var partial = String(x.st || "").indexOf("部分") >= 0;
    var tries = x.tries || 0;
    el.innerHTML = "<div class='bc-top'><span class='bc-no'>" + esc(x.no) + "</span>"
      + (partial ? "<span class='bc-tag partial'>部分</span>" : "")
      + (tries > 1 ? "<span class='bc-tag retry'>第 " + tries + " 次</span>" : "")
      + "</div><div class='bc-sub'>" + esc(x.sub) + "</div>"
      + "<div class='bc-foot'><span class='bc-role'>" + esc(x.role) + " " + esc(roleName(x.role)) + "</span>"
      + (x.lastStarted ? "<em>" + esc(String(x.lastStarted).replace("T", " ").slice(5, 16)) + "</em>" : "")
      + "</div>";
    el.title = "期望产出：" + (x.expect || "—");
    el.addEventListener("click", function(){
      state.activeSub = x.no;
      showSubOutput(x);
    });
    return el;
  }


  function runTick(){
    api("/api/run/events?since=" + state.runSeq).then(function(j){
      if (!j || !j.ok) return;
      if (j.state) state.runSeq = j.state.seq;
      (j.events || []).forEach(function(ev){ runRender(ev); });
    }).catch(function(){});
  }
  function runStepEl(turn, step, label){
    var el = document.createElement("div");
    el.className = "run-step";
    el.textContent = "▶ 回合 " + turn + (step === "-" ? "" : " · 步骤 " + step) + (label ? " · " + label : "");
    return el;
  }
  function runOutEl(turn, step){
    var el = document.createElement("div");
    el.className = "run-out";
    return el;
  }
  /* ===== 实时事件：按任务分段（run/start 起一段，直到下一个 run/start） ===== */
  var _runSec = null;   // 当前接收事件的 .run-sec（活跃段）
  function runSecNo(ev){
    var m = /(T-\d+(?:-\w+)?)/.exec(String((ev && ev.task) || "") || "");
    return m ? m[1] : "";
  }
  function toggleRunSec(sec){
    var open = sec.classList.toggle("open");
    var a = sec.querySelector(".rs-arrow");
    if (a) a.textContent = open ? "▾" : "▸";
  }
  function newRunSec(ev){
    var lg = $("runLog"); if (!lg) return null;
    var no = runSecNo(ev);
    var label = String((ev && ev.task) || "任务").replace(no, "").replace(/^[\s·｜|:：-]+/, "").slice(0, 42);
    var sec = document.createElement("div");
    sec.className = "run-sec open";
    var head = document.createElement("div");
    head.className = "run-sec-head";
    var meta = [];
    if (ev.provider) meta.push(String(ev.provider));
    if (ev.model) meta.push(String(ev.model));
    head.innerHTML = "<span class='rs-arrow'>▾</span><span class='rs-no'>" + esc(no || "事件") + "</span>"
      + "<span class='rs-label'>" + esc(label || "") + "</span>"
      + (meta.length ? "<em>" + esc(meta.join(" / ")) + "</em>" : "");
    var body = document.createElement("div");
    body.className = "run-sec-body";
    sec.appendChild(head); sec.appendChild(body);
    head.addEventListener("click", function(){ toggleRunSec(sec); });
    /* 新任务段展开，旧任务段自动收起（runLog 聚焦当前任务，点段头可展开历史） */
    Array.prototype.forEach.call(lg.querySelectorAll(".run-sec.open"), function(s){
      s.classList.remove("open"); var a = s.querySelector(".rs-arrow"); if (a) a.textContent = "▸";
    });
    lg.appendChild(sec);
    _runSec = sec;
    return body;
  }
  function runSecBody(create){
    var lg = $("runLog"); if (!lg) return null;
    if (_runSec && _runSec.isConnected && _runSec.querySelector(".run-sec-body")) return _runSec.querySelector(".run-sec-body");
    if (!create) return null;
    /* 无 run/start 前缀的事件（如外部 agent 遥测）归入通用段 */
    var sec = document.createElement("div");
    sec.className = "run-sec open";
    var head = document.createElement("div");
    head.className = "run-sec-head";
    head.innerHTML = "<span class='rs-arrow'>▾</span><span class='rs-no'>事件</span><em>未归入任务</em>";
    var body = document.createElement("div");
    body.className = "run-sec-body";
    sec.appendChild(head); sec.appendChild(body);
    head.addEventListener("click", function(){ toggleRunSec(sec); });
    lg.appendChild(sec);
    _runSec = sec;
    return body;
  }
  function dropRunSec(no){
    if (!no) return;
    var lg = $("runLog"); if (!lg) return;
    Array.prototype.forEach.call(lg.querySelectorAll(".run-sec"), function(sec){
      var h = sec.querySelector(".rs-no");
      if (h && (h.textContent || "").indexOf(no) === 0) sec.remove();
    });
    if (_runSec && !_runSec.isConnected) _runSec = null;
  }
  function runLastOut(){
    var b = runSecBody(false);
    if (!b) return null;
    var outs = b.querySelectorAll(".run-out");
    return outs.length ? outs[outs.length - 1] : null;
  }
  function runRender(ev){
    /* 事件源 = runner 缓冲（chain 只发 6 种合成事件）：run/start → 新建任务段；
       其余事件追加进当前段。 */
    var lg = $("runLog");
    if (!lg) return;
    if (lg.querySelector(".placeholder")) lg.innerHTML = "";
    var type = ev.type || "";
    var d = ev.data || {};
    var body;
    if (type === "run/start"){
      body = newRunSec(ev);
      var b = document.createElement("div");
      b.className = "run-banner";
      b.textContent = "自动执行链启动" + (ev.task ? "：" + String(ev.task) : "");
      if (body) body.appendChild(b);
    } else {
      body = runSecBody(true);
    }
    if (!body) return;
    if (type === "step/start"){
      body.appendChild(runStepEl(d.turn, d.step, ""));
      body.appendChild(runOutEl(d.turn, d.step));
    } else if (type === "assistant/chunk"){
      if (d.text != null){
        var ob = runLastOut();
        if (!ob){ ob = runOutEl("", ""); body.appendChild(ob); }
        var span = document.createElement("span");
        span.textContent = d.text;
        ob.appendChild(span);
      }
    } else if (type === "step/end"){
      body.appendChild(runStepEl(d.turn, d.step, "步骤完成"));
    } else if (type === "run/end"){
      var e4 = document.createElement("div");
      e4.className = "run-banner end";
      e4.textContent = "执行结束 · " + String((ev.text || "")).slice(0, 600);
      body.appendChild(e4);
    } else if (type === "run/exited"){
      var e5 = document.createElement("div");
      e5.className = "run-step";
      e5.textContent = "进程退出码：" + (d.code != null ? d.code : "?");
      body.appendChild(e5);
    }
    lg.scrollTop = lg.scrollHeight;
  }
  /* ================= 每日简报 ================= */
  /* ================= 角色管理 ================= */
  function parseCardFields(card){
    var o = { no: "", name: "", type: "", position: "", duty: [], skills: [] }, seg = null;
    card.split(NL10).forEach(function(ln){
      var t = ln.trim();
      if (t.indexOf("## ") === 0){ seg = t.slice(3); return; }
      if (seg === "身份"){
        if (t.indexOf("- 编号：") === 0){ t.slice(4).split("｜").forEach(function(p){ var kv = p.split("："); if (kv[0] === "编号") o.no = kv[1] || ""; if (kv[0] === "名称") o.name = kv[1] || ""; if (kv[0] === "类型") o.type = kv[1] || ""; }); }
        else if (t.indexOf("- 一句话定位：") === 0) o.position = t.slice(7).split("（")[0];
      }
      else if (seg === "职责" && t.indexOf("- ") === 0) o.duty.push(t.slice(2));
      else if (seg === "技能" && t.indexOf("- ") === 0){
        var s2 = t.slice(2).trim();
        if (s2 && s2.indexOf("（") !== 0 && s2.indexOf("(") !== 0) o.skills.push(s2);
      }
    });
    return o;
  }
  function loadRoles(){
    api("/api/roles").then(function(jj){
      if (!jj || !jj.ok) return;
      var m = state.rolesMap || {};
      (jj.roles || []).forEach(function(r){ m[r.no] = r.name; });
      state.rolesMap = m;
      var box = $("roleList"); if (!box) return; box.innerHTML = "";
      (jj.roles || []).forEach(function(rr){
        var el = document.createElement("div"); el.className = "r-item";
        var nm = document.createElement("span"); nm.className = "r-name"; nm.textContent = rr.name || rr.no;
        var idn = document.createElement("em"); idn.className = "r-no"; idn.textContent = "Id:" + rr.no;
        var btEdit = document.createElement("button"); btEdit.textContent = "编辑";
        btEdit.addEventListener("click", function(){ fillRoleForm(rr.no); });
        var btCard = document.createElement("button"); btCard.textContent = "卡";
        btCard.addEventListener("click", function(){
          api("/api/roles/card?no=" + encodeURIComponent(rr.no)).then(function(jc){ if (jc && jc.ok) showRoleCard(rr.name || rr.no, jc.card); });
        });
        el.appendChild(nm); el.appendChild(idn); el.appendChild(btEdit); el.appendChild(btCard);
        box.appendChild(el);
      });
      if (!(jj.roles || []).length){ box.innerHTML = "<div class='placeholder'>暂无角色卡——在右侧表单创建第一个角色</div>"; }
    }).catch(function(){});
  }
  function fillRoleForm(no){
    api("/api/roles/card?no=" + encodeURIComponent(no)).then(function(jc){
      if (!jc || !jc.ok) return;
      var o = parseCardFields(jc.card);
      $("rlNo").value = o.no; $("rlName").value = o.name;
      $("rlPosition").value = o.position; $("rlType").value = o.type;
      $("rlDuty").value = o.duty.join(NL10);
      $("roleMsg").textContent = "已载入 " + (o.name || o.no) + "（" + o.no + "），修改后点保存（等同编辑）。";
    }).catch(function(){});
  }
  function showRoleCard(no, card){
    var w = window.open("", "roleCard"); if (!w) return;
    w.document.write("<pre style=\"font:13px/1.6 monospace;white-space:pre-wrap\">" + esc(card) + "</pre>"); w.document.close();
  }
  function saveRole(){
    var no = $("rlNo").value.trim();
    var payload = {
      name: $("rlName").value.trim(),
      duty: $("rlDuty").value.trim(),
      position: $("rlPosition").value.trim(),
      type: $("rlType").value.trim(),
    };
    var path = no ? "/api/roles/edit" : "/api/roles/add";
    if (no) payload.no = no;
    if (!payload.name){ $("roleMsg").textContent = "名称必填"; return; }
    api(path, payload).then(function(jj){
      if (jj && jj.ok){
        var r = jj.result || {};
        $("roleMsg").textContent = (jj.preview ? "[预览] " : "") + (r.name || r.no || "") + "（" + (r.no || "") + "）已生成/更新";
        loadRoles(); cacheRoles(); loadHome();
      }
      else { $("roleMsg").textContent = "失败：" + (jj && jj.msg || "未知"); }
    }).catch(function(e){ $("roleMsg").textContent = "失败：" + e; });
  }
  function bindRoleForm(){
    var b = $("btnRoleSave"); if (b) b.addEventListener("click", saveRole);
  }

  bindRoleForm();

  /* ================= 新增/编辑角色弹窗：技能 = 从 agents/skills/ 目录勾选，不手写 = ================= */
  var _pick = { card: false, lib: false, sel: [] };
  function renderSkillPick(list){
    var box = $("mRlSkills"); if (!box) return;
    box.innerHTML = "";
    if (!list || !list.length){
      box.innerHTML = "<div class='skills-pick-empty'>agents/skills/ 下暂无技能文件 —— 把 <code>技能名.md</code> 放进该目录后重开弹窗即可勾选</div>";
      return;
    }
    list.forEach(function(n){
      var c = document.createElement("span");
      c.className = "skill-opt";
      c.textContent = skillStem(n);
      c.title = "agents/skills/" + n;
      c.dataset.name = n;
      c.addEventListener("click", function(){ c.classList.toggle("sel"); });
      box.appendChild(c);
    });
  }
  function markSkillPick(sel){
    var box = $("mRlSkills"); if (!box) return;
    box.querySelectorAll(".skill-opt").forEach(function(c){
      if (sel.indexOf(c.dataset.name) >= 0) c.classList.add("sel");
    });
  }
  function pickDone(){
    if (_pick.card && _pick.lib) markSkillPick(_pick.sel || []);
  }
  function loadSkillPick(){
    var box = $("mRlSkills");
    if (box) box.innerHTML = "<div class='skills-pick-empty'>加载技能库…</div>";
    api("/api/skills").then(function(j){
      renderSkillPick((j && j.skills) || []);
      _pick.lib = true; pickDone();
    }).catch(function(){ renderSkillPick([]); _pick.lib = true; pickDone(); });
  }
  function openRoleModal(mode, no){
    var m = $("roleModal"); if (!m) return;
    mode = mode || "add"; no = no || "";
    ["mRlName","mRlPosition","mRlType","mRlDuty"].forEach(function(id){ var el = $(id); if (el) el.value = ""; });
    _pick = { card: false, lib: false, sel: [] };
    var msg = $("mRoleMsg"); if (msg) msg.textContent = "";
    var title = $("roleModalTitle"); if (title) title.textContent = (mode === "edit") ? "编辑角色 " + no : "＋ 新增角色";
    var hint = $("roleModalHint");
    if (hint) hint.textContent = (mode === "edit")
      ? ""
      : "";
    m.dataset.mode = mode; m.dataset.no = no;
    m.hidden = false;
    if (mode === "add"){
      _pick.card = true;
    } else if (mode === "edit" && no){
      api("/api/roles/card?no=" + encodeURIComponent(no)).then(function(jc){
        if (!jc || !jc.ok){ var mm = $("mRoleMsg"); if (mm) mm.textContent = "角色卡加载失败：该角色无 " + no + ".role.md"; _pick.card = true; pickDone(); return; }
        var o = parseCardFields(jc.card || "");
        var n1 = $("mRlName"); if (n1) n1.value = o.name || "";
        var p1 = $("mRlPosition"); if (p1) p1.value = o.position || "";
        var t1 = $("mRlType"); if (t1) t1.value = o.type || "";
        var d1 = $("mRlDuty"); if (d1) d1.value = (o.duty || []).join(NL10);
        _pick.sel = o.skills || [];
        _pick.card = true; pickDone();
      }).catch(function(){ _pick.card = true; pickDone(); });
    }
    loadSkillPick();
    var n2 = $("mRlName"); if (n2) n2.focus();
  }
  function closeRoleModal(){
    var m = $("roleModal"); if (m) m.hidden = true;
  }
  function saveModalRole(){
    var m = $("roleModal");
    var mode = (m && m.dataset.mode) || "add";
    var no = (m && m.dataset.no) || "";
    var name = ($("mRlName").value || "").trim();
    var msg = $("mRoleMsg");
    if (msg) msg.textContent = "";
    if (!name){ if (msg) msg.textContent = "名称必填"; return; }
    var payload = {
      name: name,
      duty: ($("mRlDuty").value || "").trim(),
      position: ($("mRlPosition").value || "").trim(),
      type: ($("mRlType").value || "").trim(),
      skills: Array.prototype.map.call(document.querySelectorAll("#mRlSkills .skill-opt.sel"), function(el){ return el.dataset.name || ""; }).join("\n")
    };
    if (mode === "edit") payload.no = no;
    if (msg) msg.textContent = "保存中…";
    post(mode === "edit" ? "/api/roles/edit" : "/api/roles/add", payload).then(function(jj){
      if (jj && jj.ok){
        var r = jj.result || {};
        if (msg) msg.textContent = (mode === "edit" ? "✓ 已更新 " : "✓ 已创建 ") + (r.name || payload.name) + "（" + (r.no || no) + "）";
        loadRoles(); cacheRoles(); loadHome();
        if (mode === "edit" && no){ var ebtn = $("btnEditRole"); if (ebtn && ebtn.dataset.no === no) openRole(no); }
        setTimeout(closeRoleModal, 1600);
      } else {
        if (msg) msg.textContent = "失败：" + esc(jj && jj.msg || "未知");
      }
    }).catch(function(e){ if (msg) msg.textContent = "失败：" + esc(e.message); });
  }
  function bindRoleModal(){
    var a = $("orgAdd"); if (a) a.addEventListener("click", function(){ openRoleModal("add", ""); });
    var e2 = $("btnEditRole"); if (e2) e2.addEventListener("click", function(){ openRoleModal("edit", e2.dataset.no || ""); });
    var c = $("btnModalClose"); if (c) c.addEventListener("click", closeRoleModal);
    var s = $("btnModalRoleSave"); if (s) s.addEventListener("click", saveModalRole);
    var m = $("roleModal");
    if (m) m.addEventListener("click", function(e){ if (e.target === m) closeRoleModal(); });
    document.addEventListener("keydown", function(e){ if (e.key === "Escape") closeRoleModal(); });
  }
  bindRoleModal();
  function openDelRoleModal(no, name){
    var m = $("delRoleModal"); if (!m) return;
    var info = $("delRoleInfo");
    if (info) info.innerHTML = "<b>" + esc(no) + " · " + esc(name) + "</b>"
      + "<br>确认删除将永久移除："
      + "<br>① 角色卡《agents/" + esc(no) + ".role.md》"
      + "<br>③ 工作区《工作区/" + esc(name) + "/》"
      + "<br>④ 《知识库/OPC智能体角色架构.md》登记行"
      + "<br><span class='del-warn'>此操作不可恢复，请二次确认。</span>";
    var msg = $("delRoleMsg"); if (msg) msg.textContent = "";
    m.dataset.no = no; m.dataset.name = name;
    m.hidden = false;
  }
  function closeDelRoleModal(){
    var m = $("delRoleModal"); if (m) m.hidden = true;
  }
  function confirmDelRole(){
    var m = $("delRoleModal"); if (!m) return;
    var no = m.dataset.no || "";
    var msg = $("delRoleMsg");
    if (msg) msg.textContent = "删除中…";
    post("/api/roles/delete", { no: no }).then(function(jj){
      if (jj && jj.ok){
        if (msg) msg.textContent = "✓ 已删除 " + esc(m.dataset.name || "") + "（" + esc(no) + "），剩余 " + esc(jj.result && jj.result.roleLeft || "?") + " 个角色";
        cacheRoles(); loadRoles(); loadHome();
        setTimeout(closeDelRoleModal, 1600);
      } else {
        if (msg) msg.textContent = "删除失败：" + esc(jj && jj.msg || "未知");
      }
    }).catch(function(e){ if (msg) msg.textContent = "删除失败：" + esc(e.message); });
  }
  function bindDelRoleModal(){
    var x = $("btnDelClose"); if (x) x.addEventListener("click", closeDelRoleModal);
    var c = $("btnDelCancel"); if (c) c.addEventListener("click", closeDelRoleModal);
    var y = $("btnDelYes"); if (y) y.addEventListener("click", confirmDelRole);
    var m = $("delRoleModal");
    if (m) m.addEventListener("click", function(e){ if (e.target === m) closeDelRoleModal(); });
    document.addEventListener("keydown", function(e){ if (e.key === "Escape") closeDelRoleModal(); });
  }
  bindDelRoleModal();

  function loadDaily(){
    api("/api/daily").then(function(j){
      if (!j || !j.ok) return;
      state.daily = j.daily || [];
      var box = $("dailyFiles");
      box.innerHTML = "";
      if (!state.daily.length){ box.innerHTML = "<div class='placeholder'>暂无简报</div>"; return; }
      state.daily.forEach(function(d){
        var el = document.createElement("div");
        el.className = "d-card";
        el.textContent = d.name;
        el.addEventListener("click", function(){
          document.querySelectorAll(".d-card").forEach(function(x){ x.classList.remove("active"); });
          el.classList.add("active");
          $("dailyTitle").textContent = d.rel;
          $("dailyBody").innerHTML = "<div class='placeholder'>加载中…</div>";
          api("/api/md?rel=" + encodeURIComponent(d.rel)).then(function(j){ if (j && j.ok){ $("dailyBody").innerHTML = renderMd(j.text || ""); } });
        });
        box.appendChild(el);
      });
    }).catch(function(){});
  }

  /* ================= 04 项目文件：各角色工作区（按角色/任务筛选；md 渲染、文本 txt 查看、不可读不放行） ================= */
  var wsFiles = [], wsRole = "", wsTask = "", pendingWsRole = ""; function gotoRoleFiles(role){ pendingWsRole = role; var tab = document.querySelector('.tab[data-view="wsfiles"]'); if (tab){ tab.click(); } else { document.querySelectorAll(".view").forEach(function(x){ x.classList.remove("active"); }); var v = $("view-wsfiles"); if (v) v.classList.add("active"); loadWsFiles(); } }
  function wsFmtSize(n){
    n = Number(n) || 0;
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
  }
  function loadWsFiles(){
    wsRole = ""; wsTask = "";
    var rs = $("wsRoleSel"), ts = $("wsTaskSel");
    if (rs) rs.innerHTML = "<option value=''>全部角色</option>";
    if (ts) ts.innerHTML = "<option value=''>全部任务</option>";
    var box = $("wsList");
    if (box) box.innerHTML = "<div class='placeholder'>加载文件清单…</div>";
    api("/api/ws-files").then(function(j){
      if (!j || !j.ok){ if (box) box.innerHTML = "<div class='placeholder'>清单加载失败：" + esc(j && j.msg || "未知") + "</div>"; return; }
      wsFiles = j.files || [];
      var roles = [], seenR = {}, tasks = [], seenT = {}, hasNone = false;
      wsFiles.forEach(function(f){
        if (!seenR[f.role]){ seenR[f.role] = 1; roles.push(f.role); }
        if (f.task){ if (!seenT[f.task]){ seenT[f.task] = 1; tasks.push(f.task); } }
        else { hasNone = true; }
      });
      roles.sort();
      tasks.sort(function(a, b){ return parseInt(a.slice(2), 10) - parseInt(b.slice(2), 10); });
      rs.innerHTML = "<option value=''>全部角色</option>" + roles.map(function(x){ return "<option value='" + esc(x) + "'>" + esc(x) + "</option>"; }).join("");
      ts.innerHTML = "<option value=''>全部任务</option>"
        + tasks.map(function(x){ return "<option value='" + esc(x) + "'>" + esc(x) + "</option>"; }).join("")
        + (hasNone ? "<option value='__none__'>（无任务编号文件）</option>" : "");
      if (pendingWsRole){ var want = pendingWsRole; pendingWsRole = ""; if (rs && Array.prototype.some.call(rs.options, function(o){ return o.value === want; })){ rs.value = want; wsRole = want; } } renderWsList();
    }).catch(function(e){ if (box) box.innerHTML = "<div class='placeholder'>异常：" + esc(e.message) + "</div>"; });
  }
  function filteredWsFiles(){
    return wsFiles.filter(function(f){
      if (wsRole && f.role !== wsRole) return false;
      if (wsTask === "__none__"){ if (f.task) return false; }
      else if (wsTask && f.task !== wsTask) return false;
      return true;
    });
  }
  function renderWsList(){
    var box = $("wsList");
    if (!box) return;
    var rows = filteredWsFiles();
    if (!rows.length){
      box.innerHTML = "<div class='placeholder'>" + (wsFiles.length ? "没有匹配的文件（换个角色 / 任务筛选）" : "暂无文件 —— 任务执行后各角色产出会落到《工作区/<角色>/》") + "</div>";
      return;
    }
    rows.sort(function(a, b){
      return (a.role < b.role ? -1 : a.role > b.role ? 1 : 0)
        || (a.task < b.task ? -1 : a.task > b.task ? 1 : 0)
        || (a.name < b.name ? -1 : 1);
    });
    box.innerHTML = "";
    var lastRole = null;
    rows.forEach(function(f){
      if (f.role !== lastRole){
        var gh = document.createElement("div");
        gh.className = "ws-group";
        gh.textContent = "▸ " + f.role;
        box.appendChild(gh);
        lastRole = f.role;
      }
      var el = document.createElement("div");
      el.className = "ws-item";
      el.dataset.rel = f.rel;
      var meta = "";
      var k2 = f.name.indexOf("-summary.md") >= 0 ? "sum"
        : f.name.indexOf("-output.md") >= 0 ? "out"
        : f.name.indexOf("-report.md") >= 0 ? "rep"
        : (f.ext === ".md" ? "md" : "txt");
      meta += "<span class='wsi-kind k-" + k2 + "'>" + (k2 === "sum" ? "汇总" : k2 === "out" ? "产出" : k2 === "rep" ? "回报" : k2 === "md" ? "md" : "txt") + "</span>";
      if (f.archived) meta += "<span class='wsi-meta arch'>已归档</span>";
      if (f.task) meta += "<span class='wsi-meta'>" + esc(f.task) + "</span>";
      meta += "<span class='wsi-meta'>" + esc(wsFmtSize(f.size)) + "</span>";
      el.innerHTML = "<span class='wsi-role'>" + esc(f.role) + "</span>"
        + "<span class='wsi-name'>" + esc(f.name) + "</span>" + meta;
      el.title = f.rel;
      el.addEventListener("click", function(){ showWsFile(f.rel, el); });
      box.appendChild(el);
    });
  }
  function showWsFile(rel, el){
    document.querySelectorAll(".ws-item").forEach(function(x){ x.classList.remove("active"); });
    if (el) el.classList.add("active");
    $("wsTitle").textContent = rel;
    var body = $("wsBody");
    body.innerHTML = "<div class='placeholder'>加载中…</div>";
    api("/api/ws-file?rel=" + encodeURIComponent(rel)).then(function(j){
      if (!j || !j.ok){
        body.innerHTML = "<div class='ws-unread'>✕ 该文件不可读，已禁止查看：<br>" + esc(j && j.msg || "未知原因") + "</div>";
        return;
      }
      if (j.kind === "md"){
        body.innerHTML = "<div class='ws-note'>Markdown · 已渲染查看</div><div class='markdown-body'>" + renderMd(j.text || "") + "</div>";
      } else {
        body.innerHTML = "<div class='ws-note'>文本文件 · 以 txt 方式查看</div><pre class='ws-txt'>" + esc(j.text || "") + "</pre>";
      }
    }).catch(function(e){ body.innerHTML = "<div class='ws-unread'>读取失败：" + esc(e.message) + "</div>"; });
  }
  var wsRoleSel = $("wsRoleSel");
  if (wsRoleSel) wsRoleSel.addEventListener("change", function(){ wsRole = this.value; renderWsList(); });
  var wsTaskSel = $("wsTaskSel");
  if (wsTaskSel) wsTaskSel.addEventListener("change", function(){ wsTask = this.value; renderWsList(); });
  var wsRefreshBtn = $("wsRefresh");
  if (wsRefreshBtn) wsRefreshBtn.addEventListener("click", loadWsFiles);

    /* ================= Markdown 轻量渲染 ================= */
  function inlineMd(s){
    s = esc(s);
    var a = s.split("**"), out = a[0];
    for (var k = 1; k < a.length; k++){ out += (k % 2 === 1 ? "<b>" : "</b>") + a[k]; }
    var b2 = out.split("`"), out2 = b2[0];
    for (k = 1; k < b2.length; k++){ out2 += (k % 2 === 1 ? "<code>" : "</code>") + b2[k]; }
    return out2;
  }
  function renderMd(text){
    var lines = String(text || "").split(NL10);
    var out = [], inUl = false, inPre = false, buf = [];
    function closeUl(){ if (inUl){ out.push("</ul>"); inUl = false; } }
    function flushPre(){ if (inPre){ out.push("<pre><code>" + esc(buf.join(NL10)) + "</code></pre>"); buf = []; inPre = false; } }
    function isTblRow(t){ return t.charAt(0) === "|" && t.charAt(t.length - 1) === "|"; }
    function splitTblRow(r){
      var s = String(r).trim();
      if (s.charAt(0) === "|") s = s.slice(1);
      if (s.charAt(s.length - 1) === "|") s = s.slice(0, -1);
      var o2 = [], cells = s.split("|");
      for (var k2 = 0; k2 < cells.length; k2++){ o2.push(cells[k2].trim()); }
      return o2;
    }
    function mdTable(rows){
      var head = splitTblRow(rows[0]), body = [];
      for (var j2 = 1; j2 < rows.length; j2++){
        var r2 = rows[j2];
        if (r2.indexOf("-") >= 0 && /^[\s|:\-]+$/.test(r2)) continue;   // 分隔行 |---|---|
        body.push(splitTblRow(r2));
      }
      var h = "<thead><tr>";
      for (var a2 = 0; a2 < head.length; a2++){ h += "<th>" + inlineMd(head[a2]) + "</th>"; }
      h += "</tr></thead>";
      var b = "<tbody>";
      for (var c2 = 0; c2 < body.length; c2++){
        var tr = body[c2]; b += "<tr>";
        for (var d2 = 0; d2 < tr.length; d2++){ b += "<td>" + inlineMd(tr[d2]) + "</td>"; }
        b += "</tr>";
      }
      b += "</tbody>";
      return "<div class='mdt-wrap'><table class='mdt'>" + h + b + "</table></div>";
    }
    for (var i = 0; i < lines.length; i++){
      var ln = lines[i];
      var t = ln.trim();
      if (t.indexOf("```") === 0){ if (inPre){ flushPre(); } else { closeUl(); inPre = true; buf = []; } continue; }
      if (inPre){ buf.push(ln); continue; }
      if (t === ""){ closeUl(); continue; }
      if (isTblRow(t)){
        closeUl();
        var rows = [ln];
        while (i + 1 < lines.length){
          var nxt = lines[i + 1].trim();
          if (nxt === "" || !isTblRow(nxt)) break;
          rows.push(lines[i + 1]); i++;
        }
        out.push(mdTable(rows));
        continue;
      }
      if (t.indexOf("### ") === 0){ closeUl(); out.push("<h3>" + inlineMd(t.slice(4)) + "</h3>"); continue; }
      if (t.indexOf("## ") === 0){ closeUl(); out.push("<h2>" + inlineMd(t.slice(3)) + "</h2>"); continue; }
      if (t.indexOf("# ") === 0){ closeUl(); out.push("<h1>" + inlineMd(t.slice(2)) + "</h1>"); continue; }
      if (t === "---"){ closeUl(); out.push("<hr>"); continue; }
      if (t.indexOf("> ") === 0){ closeUl(); out.push("<blockquote>" + inlineMd(t.slice(2)) + "</blockquote>"); continue; }
      if (t.indexOf("- ") === 0){ if (!inUl){ out.push("<ul>"); inUl = true; } out.push("<li>" + inlineMd(t.slice(2)) + "</li>"); continue; }
      if (t.charAt(0) >= "0" && t.charAt(0) <= "9"){ closeUl(); out.push("<p>" + inlineMd(t) + "</p>"); continue; }
      closeUl();
      out.push("<p>" + inlineMd(ln) + "</p>");
    }
    closeUl(); flushPre();
    return out.join("");
  }

  /* ================= 设置：目录选择 / 配置保存 ================= */
  /* ================= 设置：项目管理（一个 opc-web 对应多个 OPC 项目） ================= */
  var dshSkills = [];
  function loadDshSkills(){
    var box = $("dshSkillList");
    if (box) box.innerHTML = "<div class='placeholder'>加载中…</div>";
    api("/api/dsh-skills").then(function(j){
      if (!j || !j.ok){ if (box) box.innerHTML = "<div class='placeholder'>加载失败：" + esc(j && j.msg || "未知") + "</div>"; return; }
      dshSkills = j.skills || [];
      renderDshSkills();
    }).catch(function(e){ if (box) box.innerHTML = "<div class='placeholder'>异常：" + esc(e.message) + "</div>"; });
  }
  function renderDshSkills(){
    var box = $("dshSkillList"); if (!box) return;
    var ss = $("skillSearch");
    var q = (ss && ss.value || "").toLowerCase();
    var list = dshSkills.filter(function(s){ return (!q || (s.name + " " + (s.desc || "")).toLowerCase().indexOf(q) >= 0); });
    if (!list.length){ box.innerHTML = "<div class='placeholder'>无匹配技能；也可用 npx skills find 搜索在线市场</div>"; return; }
    box.innerHTML = "";
    list.forEach(function(s){
      var el = document.createElement("div");
      el.className = "skill-import-item";
      el.innerHTML = "<div class='skill-import-info'><b>" + esc(s.name) + "</b><em>" + esc(s.desc || "") + "</em></div>"
        + (s.installed ? "<span class='skill-import-st done'>已导入</span>" : "<button class='skill-import-btn'>导入</button>");
      var btn = el.querySelector(".skill-import-btn");
      if (btn) btn.addEventListener("click", function(){ importDshSkill(s.name); });
      box.appendChild(el);
    });
  }
  function importDshSkill(name){
    post("/api/skill-import", {name: name}).then(function(j){
      if (j && j.ok){ dshSkills = j.skills || []; renderDshSkills(); var m = $("skillMsg"); if (m) m.textContent = (j.msg || "已导入"); }
      else { alert((j && j.msg) || "导入失败"); }
    }).catch(function(e){ alert("导入失败：" + (e.message || "")); });
  }
  function loadSettings(){
    api("/api/settings").then(function(j){
      if (!j || !j.ok){ var m = $("setMsg"); if (m) m.textContent = "读取设置失败：" + esc(j && j.msg || "未知"); return; }
      var mi = j.model || {};
      var mp = $("mApiProvider"); if (mp) mp.value = mi.provider || "deepseek";
      var ak = $("mApiKey"); if (ak) ak.value = "";
      var ab = $("mApiBase"); if (ab) ab.value = mi.baseURL || "";
      var am = $("mApiModel"); if (am) am.value = mi.model || "";
      var an = $("mApiNote");
      if (an) an.innerHTML = "<b>接入方式（同 dsh 模型 API）</b> 提供方 <code>" + esc(mi.provider || "deepseek") + "</code> → 凭据引用 <code>" + esc(mi.apiKeyEnv || "") + "</code><br>密钥状态：" + (mi.configured ? "已配置 ✓" : "未配置 — 密钥只写项目根 .env，不回显");
      if (j.envOverride && j.activeProject && $("setMsg")) $("setMsg").textContent = "环境变量（OPC_KB_ROOT/OPC_CONFIG/OPC_PORT）优先于配置，请直接手改 opc-config.json";
      loadSchedules();
      loadRoles();
      loadProjects();
    }).catch(function(e){ var m = $("setMsg"); if (m) m.textContent = "异常：" + esc(e.message); });
  }
  function loadProjects(){
    api("/api/projects").then(function(j){
      if (!j || !j.ok) return;
      var box = $("projList");
      if (!box) return;
      var list = j.projects || [];
      var active = (j.active || {}).root || "";
      var seed = j.seedRoles || 0;
      if (!list.length){
        box.innerHTML = "<div class='placeholder'>还没有项目 —— 在右侧填入项目名 + 目录，点「＋ 新建项目」（首个会自动激活，角色阵容从 agents-seed 复制 " + seed + " 张卡）</div>";
      } else {
        box.innerHTML = "";
        list.forEach(function(p){
          var el = document.createElement("div");
          el.className = "proj-item" + (p.root === active ? " active" : "");
          el.innerHTML = "<span class='pj-name'>" + esc(p.name || "") + "</span>"
            + "<span class='pj-root'>" + esc(p.root || "") + "</span>"
            + "<em class='pj-st'>" + (p.root === active ? "● 当前" : "") + "</em>"
            + (p.root !== active
                ? "<button class='mini pj-use'>切换</button>"
                : "<button class='mini pj-rm danger' title='只移出登记，不删任何数据'>移除</button>");
          var use = el.querySelector(".pj-use");
          if (use) use.addEventListener("click", function(){ projectAction("switch", p.root, ""); });
          var rm = el.querySelector(".pj-rm");
          if (rm) rm.addEventListener("click", function(){
            if (confirm("把项目「" + (p.name || "") + "」移出登记？项目目录与其中的数据不会删除。")) projectAction("remove", p.root, "");
          });
          box.appendChild(el);
        });
      }
      renderProjectSwitcher(list, active);
    }).catch(function(){});
  }
  function renderProjectSwitcher(list, active){
    var sel = $("projSel");
    if (!sel) return;
    sel.innerHTML = "";
    if (!list.length){
      var o0 = document.createElement("option");
      o0.textContent = "（未建项目 · 去设置）";
      sel.appendChild(o0);
      return;
    }
    list.forEach(function(p){
      var o = document.createElement("option");
      o.value = p.root || "";
      o.textContent = p.name || p.root || "";
      o.selected = p.root === active;
      sel.appendChild(o);
    });
  }
  function addProject(){
    var m = $("projMsg");
    var name = ($("projName").value || "").trim();
    var root = ($("projRoot").value || "").trim().replace(/\\/g, "/");   // Windows 反斜杠 → /，否则 JSON 转义崩
    if (!root){ if (m) m.textContent = "项目目录必填（绝对路径，如 D:/opc/keeptalk）"; return; }
    if (m) m.textContent = "创建中…";
    projectAction("add", root, name);
  }
  function projectAction(action, root, name){
    var m = $("projMsg");
    root = String(root || "").replace(/\\/g, "/");   // 同上：统一正斜杠进 JSON
    post("/api/projects", { action: action, root: root, name: name }).then(function(j){
      if (!j || !j.ok){
        if (m) m.textContent = (action === "switch" ? "切换失败" : action === "add" ? "新建失败" : "移除失败") + "：" + esc(j && j.msg || "未知");
        return;
      }
      if (m) m.textContent = action === "add" ? "✓ 项目已创建并激活" : action === "switch" ? "✓ 已切换到 " + esc((j.project || {}).name || "") : "✓ 已移出登记";
      ["projName","projRoot"].forEach(function(id){ var el = $(id); if (el) el.value = ""; });
      loadProjects();
      loadSettings();
      loadHome();
      loadQueue();
      loadBoard();
    }).catch(function(e){ if (m) m.textContent = "异常：" + esc(e.message); });
  }


  /* ================= 设置：任务 Token 统计（输入/输出柱状，数据来自 meta.json） ================= */
  function fmtTok(n){
    n = Number(n) || 0;
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(1) + "k";
    return String(n);
  }
  function loadTokenStats(){
    var sum = $("tokSum"), chart = $("tokChart");
    if (sum) sum.textContent = "";
    if (chart) chart.innerHTML = "<div class='placeholder'>加载中…</div>";
    api("/api/tokens").then(function(j){
      if (!j || !j.ok){ if (chart) chart.innerHTML = "<div class='placeholder'>读取失败：" + esc(j && j.msg || "未知") + "</div>"; return; }
      var rows = j.rows || [];
      if (!rows.length){
        if (chart) chart.innerHTML = "<div class='placeholder'>暂无 token 数据 —— 启用 token 统计后执行的任务会写入 meta.json</div>";
        return;
      }
      var byTask = {}, tIn = 0, tOut = 0;
      rows.forEach(function(x){
        tIn += x.tokensIn || 0; tOut += x.tokensOut || 0;
        var t = x.task || "(无任务)";
        if (!byTask[t]) byTask[t] = { inn: 0, out: 0, subs: 0 };
        byTask[t].inn += x.tokensIn || 0; byTask[t].out += x.tokensOut || 0; byTask[t].subs++;
      });
      var names = Object.keys(byTask).sort(function(a, b){
        var ia = parseInt(a.slice(2), 10), ib = parseInt(b.slice(2), 10);
        return (isNaN(ia) ? 0 : ia) - (isNaN(ib) ? 0 : ib);
      });
      var max = 0;
      names.forEach(function(t){ max = Math.max(max, byTask[t].inn + byTask[t].out); });
      max = max || 1;
      if (sum) sum.innerHTML = "共 <b>" + rows.length + "</b> 个子任务 · 总输入 <b>" + fmtTok(tIn) + "</b> · 总输出 <b>" + fmtTok(tOut) + "</b> · 输入:输出 " + Math.round(tOut / (tIn || 1) * 100) + "%";
      var bars = names.map(function(t){
        var v = byTask[t];
        var hIn = Math.max(2, Math.round(v.inn / max * 180));
        var hOut = Math.max(2, Math.round(v.out / max * 180));
        return "<div class='tok-col'><div class='tok-bars'>"
          + "<span class='tok-bar in' style='height:" + hIn + "px' title='" + esc(t) + " 输入 " + fmtTok(v.inn) + "'></span>"
          + "<span class='tok-bar out' style='height:" + hOut + "px' title='" + esc(t) + " 输出 " + fmtTok(v.out) + "'></span>"
          + "</div><div class='tok-lab'>" + esc(t) + "</div><div class='tok-val'>" + fmtTok(v.inn + v.out) + "</div></div>";
      }).join("");
      chart.innerHTML = "<div class='tok-legend'><span class='lg-in'>输入</span><span class='lg-out'>输出</span></div>"
        + "<div class='tok-zone'>" + bars + "</div>";
    }).catch(function(e){ if (chart) chart.innerHTML = "<div class='placeholder'>异常：" + esc(e.message) + "</div>"; });
  }

  function bindSettings(){
    document.querySelectorAll(".snav-item").forEach(function(item){
      item.addEventListener("click", function(){
        var k = item.getAttribute("data-snav");
        document.querySelectorAll(".snav-item").forEach(function(x){ x.classList.remove("active"); });
        item.classList.add("active");
        document.querySelectorAll(".snav-pane").forEach(function(p){ p.classList.remove("active"); });
        var pane = document.querySelector('.snav-pane[data-pane="' + k + '"]');
        if (pane) pane.classList.add("active");
        if (k === "tokens") loadTokenStats();
        if (k === "skill") loadDshSkills();
      });
    });
    var sss = $("skillSearch"); if (sss && !sss.dataset.bound){ sss.dataset.bound = "1"; sss.addEventListener("input", renderDshSkills); }
    var ps = $("projSel");
    if (ps && !ps.dataset.bound){
      ps.dataset.bound = "1";
      ps.addEventListener("change", function(){
        if (ps.value) projectAction("switch", ps.value, "");
      });
    }
    var pa = $("btnProjAdd"); if (pa) pa.addEventListener("click", addProject);
    var bm = $("btnSaveModelApi"); if (bm) bm.addEventListener("click", saveModelApi);
    var bt = $("btnTestModelApi"); if (bt) bt.addEventListener("click", testModelApi);
    var mpv = $("mApiProvider"); if (mpv) mpv.addEventListener("change", modelProviderChanged);
    var sa = $("btnSchedAdd"); if (sa) sa.addEventListener("click", addSched);
    var bb = $("btnBrowseDir"); if (bb) bb.addEventListener("click", dirOpen);
    var dcl = $("btnDirClose"); if (dcl) dcl.addEventListener("click", dirClose);
    var dup = $("btnDirUp"); if (dup) dup.addEventListener("click", function(){ if (DIR.parent) dirLoad(DIR.parent); });
    var dpk = $("btnDirPick"); if (dpk) dpk.addEventListener("click", dirPick);
    var dm = $("dirModal");
    if (dm) dm.addEventListener("click", function(e){ if (e.target === dm) dirClose(); });
    document.addEventListener("keydown", function(e){ if (e.key === "Escape") dirClose(); });
  }

  /* ================= 目录选择器（设置 → 项目） ================= */
  var DIR = { path: "", parent: "" };
  function dirOpen(){
    DIR = { path: "", parent: "" };
    var m = $("dirModal");
    if (m){ m.hidden = false; dirLoad(""); }
  }
  function dirLoad(p){
    api("/api/dirs?path=" + encodeURIComponent(p || "")).then(function(j){
      var msg = $("dirMsg");
      if (!j || !j.ok){ if (msg) msg.textContent = (j && j.msg) || "加载失败"; return; }
      DIR.path = j.path || ""; DIR.parent = j.parent || "";
      var cur = $("dirCurrent"); if (cur) cur.textContent = DIR.path || "（磁盘根）";
      var list = $("dirList"); if (!list) return;
      list.innerHTML = "";
      var dirs = j.dirs || [];
      if (!dirs.length){
        list.innerHTML = "<div class='dir-empty'>（无子目录）</div>";
      }
      dirs.forEach(function(d){
        var el = document.createElement("div");
        el.className = "dir-item";
        el.innerHTML = "<span class='dir-ico'>▸</span><span class='dir-name'>" + esc(d) + "</span>";
        el.addEventListener("click", function(){
          dirLoad(DIR.path ? DIR.path.replace(/\/+$/, "") + "/" + d : d);
        });
        list.appendChild(el);
      });
      var up = $("btnDirUp"); if (up) up.disabled = !DIR.parent;
      if (msg) msg.textContent = "";
    });
  }
  function dirPick(){
    var v = $("projRoot");
    if (v && DIR.path) v.value = DIR.path;
    dirClose();
  }
  function dirClose(){
    var m = $("dirModal");
    if (m) m.hidden = true;
  }

  function schedDesc(j){
    var d = ["周一","周二","周三","周四","周五","周六","周日"];
    if (j.mode === "interval") return "每 " + (j.intervalMin || "—") + " 分钟一次";
    if (j.mode === "weekly") return "每周" + ((d[+j.weekday]) || "?") + " " + (j.time || "");
    return "每天 " + (j.time || "");
  }
  function loadSchedules(){
    api("/api/schedule").then(function(jj){
      var box = $("schedList"); if (!box) return;
      if (!jj || !jj.ok){ box.innerHTML = "<div class='placeholder'>定时任务读取失败：" + esc(jj && jj.msg || "未知") + "</div>"; return; }
      box.innerHTML = "";
      var jobs = jj.schedules || [];
      if (!jobs.length){ box.innerHTML = "<div class='placeholder'>暂无定时任务 —— 在右侧表单创建第一个（到点自动下达队列，由 R1 执行）</div>"; return; }
      jobs.forEach(function(s){
        var el = document.createElement("div");
        el.className = "sched-item";
        var badge = "<span class='sched-badge " + (s.enabled ? "on" : "off") + "'>" + (s.enabled ? "● 启用" : "○ 停用") + "</span>";
        var mode = "<span class='sched-mode'>" + esc(schedDesc(s)) + "</span>";
        var sid = "<span class='sched-id'>" + esc(s.id || "") + "</span>";
        el.innerHTML = "<div class='sched-top'>" + badge + mode + sid + "</div>"
          + "<div class='sched-task'>" + esc(s.task) + "</div>"
          + "<div class='sched-meta'><span>下次 " + esc(s.nextRun || "—") + "</span><span>上次 " + esc(s.lastRun || "从未触发") + "</span></div>"
          + "<div class='sched-ops'><button class='sched-btn-on'>" + (s.enabled ? "⏸ 停用" : "▶ 启用") + "</button>"
          + "<button class='sched-btn-off'>删除</button></div>";
        var bs = el.querySelectorAll("button");
        bs[0].addEventListener("click", function(){ toggleScheduleJob(s.id, !s.enabled); });
        bs[1].addEventListener("click", function(){ delSched(s.id); });
        box.appendChild(el);
      });
    }).catch(function(e){ var box = $("schedList"); if (box) box.innerHTML = "<div class='placeholder'>异常：" + esc(e.message) + "</div>"; });
  }
  function addSched(){
    var msg = $("schedMsg");
    var task = ($("schedTask").value || "").trim();
    if (!task){ if (msg) msg.textContent = "任务指令必填"; return; }
    var payload = {
      action: "add",
      task: task,
      mode: ($("schedMode").value || "daily").trim(),
      time: ($("schedTime").value || "").trim(),
      weekday: ($("schedWeekday").value || "").trim(),
      intervalMin: ($("schedInterval").value || "").trim()
    };
    if (msg) msg.textContent = "添加中…";
    post("/api/schedule", payload).then(function(jj){
      if (jj && jj.ok){
        if (msg) msg.textContent = "✓ 定时任务已添加 —— 到点自动下达《任务下达队列》并生成调度指令，交常驻主会话 R1 执行";
        ["schedTask","schedTime","schedWeekday","schedInterval"].forEach(function(id){ var el = $(id); if (el) el.value = ""; });
        loadSchedules();
      } else { if (msg) msg.textContent = "添加失败：" + esc(jj && jj.msg || "未知"); }
    }).catch(function(e){ if (msg) msg.textContent = "异常：" + esc(e.message); });
  }
  function toggleScheduleJob(id, enabled){
    post("/api/schedule", { action: "toggle", id: id }).then(function(jj){
      loadSchedules();
      var msg = $("schedMsg"); if (msg) msg.textContent = "✓ 已" + (enabled ? "启用" : "停用") + "定时任务 " + esc(id || "");
    }).catch(function(e){ var msg = $("schedMsg"); if (msg) msg.textContent = "异常：" + esc(e.message); });
  }
  function delSched(id){
    post("/api/schedule", { action: "delete", id: id }).then(function(jj){
      loadSchedules();
      var msg = $("schedMsg"); if (msg) msg.textContent = "✓ 已删除定时任务 " + esc(id || "");
    }).catch(function(e){ var msg = $("schedMsg"); if (msg) msg.textContent = "异常：" + esc(e.message); });
  }

  /* ================= 设置：大模型 API（模型接入，同 dsh 模型 API 接入惯例） ================= */
  function saveModelApi(){
    var m = $("mApiMsg"); if (m) m.textContent = "保存中…";
    var apiKey = ($("mApiKey").value || "").trim();
    var payload = { model: {
      provider: ($("mApiProvider").value || "deepseek").trim(),
      baseURL: ($("mApiBase").value || "").trim(),
      model: ($("mApiModel").value || "").trim()
    } };
    if (apiKey) payload.model.apiKey = apiKey;
    post("/api/settings", payload).then(function(j){
      if (j && j.ok){
        var mi = j.model || {};
        if (m) m.textContent = "✓ 模型 API 配置已保存：提供方 " + esc(mi.provider) + " · 引用 " + esc(mi.apiKeyEnv)
          + (apiKey ? " · 密钥已写入项目根 .env（不回显）" : " · 密钥保持已配置值不变")
          + (mi.configured ? "（状态：已配置 ✓）" : "（状态：未配置 — 保存密钥后 dsh 会话/subagent 自动继承）");
        var ak = $("mApiKey"); if (ak) ak.value = "";
        loadSettings();
      } else { if (m) m.textContent = "保存失败：" + esc(j && j.msg || "未知"); }
    }).catch(function(e){ if (m) m.textContent = "异常：" + esc(e.message); });
  }
  function testModelApi(){
    var m = $("mApiMsg"); if (m) m.textContent = "正在发起真实连通测试（1 token）…";
    var payload = {
      provider: ($("mApiProvider").value || "deepseek").trim(),
      baseURL: ($("mApiBase").value || "").trim(),
      model: ($("mApiModel").value || "").trim()
    };
    var apiKey = ($("mApiKey").value || "").trim();
    if (apiKey) payload.apiKey = apiKey;   // 仅本次测试使用；未填则用已存 .env 密钥
    post("/api/model/test", payload).then(function(j){
      if (j && j.ok){ if (m) m.textContent = "✓ 连通正常：" + esc(j.baseURL) + " · 模型 " + esc(j.model) + " · " + (j.latencyMs != null ? j.latencyMs + " ms" : ""); }
      else { if (m) m.textContent = "✗ 测试失败：" + esc(j && j.msg || "未知"); }
    }).catch(function(e){ if (m) m.textContent = "异常：" + esc(e.message); });
  }
  function modelProviderChanged(){
    var pv = $("mApiProvider"); if (!pv) return;
    var hint = {
      deepseek:  { env: "DEEPSEEK_API_KEY",  base: "https://api.deepseek.com",       mdl: "deepseek-chat" },
      openai:    { env: "OPENAI_API_KEY",    base: "https://api.openai.com/v1",      mdl: "gpt-4o-mini" },
      anthropic: { env: "ANTHROPIC_API_KEY", base: "https://api.anthropic.com/v1",   mdl: "claude-sonnet-4-5" },
      custom:    { env: "CUSTOM_API_KEY",    base: "https://…（自定义 OpenAI 兼容端点）", mdl: "你的模型 Id" }
    }[pv.value] || { env: "CUSTOM_API_KEY", base: "", mdl: "" };
    var ab = $("mApiBase"); if (ab && !ab.value.trim()) ab.placeholder = hint.base;
    var am = $("mApiModel"); if (am && !am.value.trim()) am.placeholder = hint.mdl;
    var an = $("mApiNote");
    if (an) an.innerHTML = "<b>接入方式（同 dsh 模型 API）</b> 提供方 <code>" + esc(pv.value) + "</code> → 凭据引用 <code>" + hint.env + "</code>（密钥只写项目根 <code>.env</code>，不回显、不落 opc-config.json 明文）";
  }

  /* ================= 视图切换 ================= */
  document.querySelectorAll(".tab").forEach(function(tab){
    tab.addEventListener("click", function(){
      var v = this.getAttribute("data-view");
      document.querySelectorAll(".tab").forEach(function(t){ t.classList.remove("active"); });
      this.classList.add("active");
      document.querySelectorAll(".view").forEach(function(x){ x.classList.remove("active"); });
      $("view-" + v).classList.add("active");
      if (v === "home") loadHome();
      if (v === "piyue") loadPiyue();
      if (v === "wsfiles") loadWsFiles();
      if (v === "kb") loadKbEntries();
      if (v === "daily") loadDaily();
      if (v === "workbench") loadWorkbench(); else liveStop();   // 离开工作台就停掉事件轮询
      if (v === "settings") loadSettings();
    });
  });

  /* ================= 主题切换（右上角按钮 · localStorage 记忆） ================= */
  function applyTheme(t){
    document.documentElement.setAttribute("data-theme", t === "dark" ? "dark" : "light");
    var b = document.getElementById("btnTheme");
    if (b) b.textContent = t === "dark" ? "浅色" : "深色";
    try { localStorage.setItem("opcTheme", t); } catch(e){}
  }
  function toggleTheme(){
    var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    applyTheme(cur === "dark" ? "light" : "dark");
  }

  /* ================= 启动 ================= */
  var savedTheme = "light";
  try { savedTheme = localStorage.getItem("opcTheme") || "light"; } catch(e){}
  applyTheme(savedTheme);
  var tb = document.getElementById("btnTheme");
  if (tb) tb.addEventListener("click", toggleTheme);
  setInterval(tick, 30000);
  tick();
  loadHome();
  bindSettings();
  loadProjects();   // 启动即拉项目清单：顶栏项目切换器一直显示正确项目名，而不是等进设置
})();