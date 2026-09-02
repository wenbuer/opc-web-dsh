# -*- coding: utf-8 -*-
import subprocess, sys
REPO = r"C:\Users\wenbu\Desktop\Projects\[2608]OPC-APP\opc-web"
def git(*a, check=True):
    r = subprocess.run(["git"] + list(a), cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        print("FAILED git", " ".join(a)); print(r.stdout); print(r.stderr); sys.exit(1)
    return (r.stdout or "") + (r.stderr or "")

git("add", "-A")
title = "\u79fb\u9664 DSH preset \u901a\u9053\uff1a\u5b83\u4ece\u672a\u53c2\u4e0e\u8fc7\u81ea\u52a8\u6d3e\u53d1"
body = (
"agents/presets-src/ \u4e0e ~/.dsh/.agent-presets/ \u7684\u6574\u5957 preset \u8d44\u4ea7\u5220\u9664\u3002\n"
"\u539f\u8bbe\u8ba1\uff08agent.py \u7684\u300c\u4e09\u901a\u9053\u300d\u6ce8\u91ca\uff09\u60f3\u8ba9\u300c\u4f1a\u8bdd\u9009\u62e9 preset \u2192 \u6d3e\u51fa\u7684\u5b50 agent \u81ea\u52a8\n"
"\u7ee7\u627f\u89d2\u8272 persona\u300d\uff0c\u4f46\u8fd9\u6761\u8def\u903b\u8f91\u4e0a\u5c31\u4e0d\u6210\u7acb\uff1a\n\n"
"- subagent \u7ee7\u627f\u7684\u662f\u7236\u4f1a\u8bdd\uff08R1 \u67a2\u7ebd\uff09\u7684 preset\uff0c\u4e0d\u662f\u76ee\u6807\u89d2\u8272\u7684\uff0c\u65b9\u5411\u53cd\u4e86\n"
"- subagent \u5de5\u5177\u672c\u8eab\u6ca1\u6709\u6307\u5b9a preset \u7684\u53c2\u6570\uff0cR1 \u65e0\u4ece\u6307\u5b9a\n"
"- \u5b9e\u6d4b ~/.dsh/.agent-presets/ \u4e0b\u53ea\u6709\u7b2c\u4e09\u65b9\u63d2\u4ef6\u7684\u9884\u8bbe\uff0c9 \u4e2a opc-r* \u4e00\u4e2a\u90fd\u6ca1\u90e8\u7f72\u8fc7\n\n"
"\u89d2\u8272 persona \u5b9e\u9645\u4e00\u76f4\u53ea\u9760 agent_prompt() \u628a\u89d2\u8272\u5361\u5168\u6587\u6ce8\u5165 prompt \u751f\u6548\uff0c\n"
"\u5220\u6389 preset \u5bf9\u6d3e\u53d1\u94fe\u8def\u96f6\u5f71\u54cd\u3002\n\n"
"\u5220\u9664\uff1a\n"
"- agent.PRESET_SRC / PRESET_HOME / role_preset() / preset_meta()\n"
"- roles.extract_persona() / preset_files() / _deploy() / generate_all()\n"
"- agents/presets-src/\uff0818 \u4e2a\u6587\u4ef6\uff09\n"
"- POST /api/roles/generate\u3001CLI \u7684 roles generate \u5b50\u547d\u4ee4\n"
"- settings_info \u7684 presetHome/presetsReady\u3001bootstrap \u7684 preset \u68c0\u6d4b\n"
"- \u524d\u7aef syncPresets()\uff08index.html \u91cc\u6839\u672c\u6ca1\u6709\u5bf9\u5e94\u6309\u94ae\uff0c\u4e00\u76f4\u662f\u6b7b\u4ee3\u7801\uff09\n\n"
"\u987a\u5e26\u4fee\u590d\uff1aedit_role \u5220\u6389 preset \u8c03\u7528\u540e\u9057\u7559\u7684 extract_persona \u60ac\u7a7a\u5f15\u7528\n"
"\uff08\u7f16\u8f91\u89d2\u8272\u4e00\u8c03\u5c31 NameError\uff09\uff1bchain.py docstring \u91cc\u89e6\u53d1\u7684 SyntaxWarning\u3002\n"
"subtask_spec \u7684 preset/presetName \u5b57\u6bb5\u6362\u6210 roleName\u3002")
git("commit", "-m", title, "-m", body)
print(git("log", "--oneline", "-1"))
print("--- \u672c\u6b21\u53d8\u66f4 ---")
print(git("-c", "core.quotepath=false", "diff", "--stat", "HEAD~1..HEAD").strip().split("\n")[-1])
leak = git("-c", "core.quotepath=false", "diff", "--name-only", "HEAD~1..HEAD")
bad = [l for l in leak.split("\n") if l.strip() and (l.endswith(".env") or "opc-config" in l or l.endswith(".db"))]
print("\u654f\u611f\u6587\u4ef6:", bad or "\u65e0")
