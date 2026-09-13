# EasyRedo

用于整理中文小学数学错题的 Codex Skill。把指定或标记的题目照片、扫描件、PDF整理为干净的题目册和对应参考答案册，保留来源、原页码与题号。

技能名：`organize-math-mistakes`，界面名称：**小学数学错题整理**。

## 内容

- [技能主说明](skills/organize-math-mistakes/SKILL.md)：执行顺序、默认要求、各阶段完成标准。
- [输入与转写](skills/organize-math-mistakes/references/01-intake-and-transcription.md)：按标记选小题、来源记录、印刷与手写分离。
- [题图处理](skills/organize-math-mistakes/references/02-figures-and-cleanup.md)：裁剪、点阵、数轴、立体积木、计数表与遮挡信息。
- [数学核验](skills/organize-math-mistakes/references/03-math-verification.md)：数量关系、连乘、可能值、多解与应用题核验。
- [PDF生成](skills/organize-math-mistakes/references/04-pdf-production.md)：数据格式、工具调用、字体、分页与故障处理。
- [交付检查](skills/organize-math-mistakes/references/05-quality-checks.md)：选题、文字、图形、答案与逐页排版检查。

另附排版脚本、9项工具行为测试、可运行的题目数据及其局部示例图片。

## 安装到 Codex

下载或克隆本仓库，将整个 `skills/organize-math-mistakes` 文件夹复制到个人技能目录。Windows通常为：

```text
C:\Users\你的用户名\.codex\skills\organize-math-mistakes
```

若配置了 `CODEX_HOME`，则复制到其 `skills` 子目录。请保留技能文件夹内的 `references`、`scripts`、`assets` 和 `agents`，不要只复制 `SKILL.md`。

下面是从仓库根目录运行的 PowerShell 安装示例。已有同名技能时会停止，便于先比较版本和保留本地修改。

```powershell
$personalSkills = if ($env:CODEX_HOME) {
    Join-Path $env:CODEX_HOME 'skills'
} else {
    Join-Path $env:USERPROFILE '.codex\skills'
}
$targetSkill = Join-Path $personalSkills 'organize-math-mistakes'
if (Test-Path -LiteralPath $targetSkill) {
    throw '已存在同名技能，请先比较并备份需要保留的本地修改。'
}
New-Item -ItemType Directory -Path $personalSkills -Force | Out-Null
Copy-Item -LiteralPath '.\skills\organize-math-mistakes' -Destination $targetSkill -Recurse
```

## 使用

在新任务中附上题目材料，并输入：

```text
请使用 $organize-math-mistakes 整理这些题目，按标记选题，保留原页码题号，生成干净题目版和对应答案版。
```

调用的 agent 需要具备看图、读写文件和执行脚本的能力。详细步骤与检查表适合较低能力模型参考；识别、选题和数学核验由 agent 执行，附带脚本负责将已核对数据排成 PDF。

## 运行排版示例

在仓库根目录执行。需要可用的 Python 与中文 TrueType 字体；Windows上工具会尝试微软雅黑或宋体，其他环境可通过 `--font` 指定兼容字体。

```powershell
python -m pip install -r requirements.txt
python -X utf8 skills/organize-math-mistakes/scripts/build_workbook.py skills/organize-math-mistakes/assets/example-questions.json --output-dir output/example
```

默认生成题目 PDF、答案 PDF 和生成记录。重复运行同名输出时工具会停止，可换输出目录；确认需要替换示例结果时添加 `--overwrite`。

正式任务使用本批核对后的 JSON 与题图，示例仅用于了解格式和验证运行环境。存在无法辨认的题时记录待核对；使用 `--draft` 可生成带明确标记的草稿。

生成后用可用的 PDF 渲染工具逐页查看。Poppler的 `pdftoppm` 可用于将页面转换成图片。

## 测试

```powershell
python -X utf8 skills/organize-math-mistakes/scripts/test_build_workbook.py
```

9项测试覆盖题目答案分离、小题编号、跨教材编号、重复输入、待核对草稿、缺失图片、已有文件保护、长文分页和过宽算式。它们验证排版工具行为，不能代替对新题原图、答案和最终页面的检查。

## 维护

以 `skills/organize-math-mistakes` 为版本管理的技能来源。修改后运行相关检查，再同步到个人技能目录。新的题目原图、作答记录与生成 PDF 放在各自任务目录中。
