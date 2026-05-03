"""将 pytest JUnit XML 转换为规范的 Markdown 测试报告。

用法：
    python tests/_report_to_md.py [xml_path] [--baseline-xml baseline_path]

默认读取 logs/pytest-latest.xml，输出到 stdout。
带 --baseline-xml 时会对比基线，标记新增/消失的失败。
"""
from __future__ import annotations

import io
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def parse_junit(xml_path: str) -> dict:
    """解析 JUnit XML，提取测试统计信息。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # 处理 testsuites 根或 testsuite 根
    if root.tag == "testsuites":
        total = int(root.get("tests", "0"))
        failures = int(root.get("failures", "0"))
        errors = int(root.get("errors", "0"))
        skipped = int(root.get("skipped", "0"))
        time = float(root.get("time", "0"))
        suites = root.findall("testsuite")
    else:
        # 单 testsuite
        total = int(root.get("tests", "0"))
        failures = int(root.get("failures", "0"))
        errors = int(root.get("errors", "0"))
        skipped = int(root.get("skipped", "0"))
        time = float(root.get("time", "0"))
        suites = [root]

    passed = total - failures - errors - skipped

    # 收集失败详情
    failed_cases: list[dict] = []
    for suite in suites:
        for case in suite.findall("testcase"):
            classname = case.get("classname", "")
            name = case.get("name", "")
            full_name = f"{classname}::{name}" if classname else name
            failure = case.find("failure")
            error = case.find("error")
            skip = case.find("skipped")

            if failure is not None:
                msg = failure.get("message", "")
                failed_cases.append({
                    "name": full_name,
                    "file": case.get("file", ""),
                    "type": "FAILED",
                    "message": msg.splitlines()[0] if msg else "AssertionError",
                })
            elif error is not None:
                msg = error.get("message", "")
                failed_cases.append({
                    "name": full_name,
                    "file": case.get("file", ""),
                    "type": "ERROR",
                    "message": msg.splitlines()[0] if msg else "Error",
                })

    return {
        "total": total,
        "passed": passed,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
        "time": time,
        "failed_cases": failed_cases,
    }


def load_baseline_failures(xml_path: str | None) -> set[str]:
    """加载基线中的失败用例名。"""
    if not xml_path or not Path(xml_path).exists():
        return set()
    data = parse_junit(xml_path)
    return {c["name"] for c in data["failed_cases"]}


def generate_report(data: dict, baseline_data: dict | None = None) -> str:
    """生成 Markdown 格式测试报告。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    failed = data["failed"]
    errors = data["errors"]
    passed = data["passed"]
    skipped = data["skipped"]
    total = data["total"]
    time = data["time"]

    # 对比基线
    baseline_fails = set()
    if baseline_data:
        baseline_fails = {c["name"] for c in baseline_data["failed_cases"]}

    lines = [
        f"## 测试报告（{now}）",
        "",
        "- **范围**：`pytest tests/ --ignore-glob=\"tests/_*.py\" --ignore-glob=\"tests/verify_*.py\"`",
        f"- **汇总**：`{passed} passed, {failed} failed, {errors} errors, {skipped} skipped`（共 {total} 用例）",
        f"- **耗时**：`{time:.2f} s`",
        "- **JUnit XML**：`logs/pytest-latest.xml`",
        "",
    ]

    if data["failed_cases"]:
        lines.append("### 失败清单")
        lines.append("")
        lines.append("| 用例 | 类型 | 原因摘要 | 基线状态 |")
        lines.append("|------|------|---------|----------|")
        for c in data["failed_cases"]:
            name = c["name"]
            file_hint = c["file"].replace("tests/", "").replace(".py", "") if c["file"] else ""
            # 简化显示：只保留文件名::类::方法
            display_name = name if "::" in name else f"{file_hint}::{name}"
            status = "已知失败" if name in baseline_fails else "⚠️ **新增失败**"
            msg = c["message"][:60] + "..." if len(c["message"]) > 60 else c["message"]
            lines.append(f"| `{display_name}` | {c['type']} | {msg} | {status} |")
        lines.append("")
    else:
        lines.append("### 失败清单")
        lines.append("")
        lines.append("无")
        lines.append("")

    # 回归检查
    lines.append("### 回归检查")
    lines.append("")
    if baseline_fails:
        current_fails = {c["name"] for c in data["failed_cases"]}
        disappeared = baseline_fails - current_fails
        new_fails = current_fails - baseline_fails
        if disappeared:
            lines.append(f"- ✅ **基线失败已修复**：{', '.join(disappeared)}")
        if new_fails:
            lines.append(f"- ⚠️ **新增失败需处理**：{', '.join(new_fails)}")
        if not disappeared and not new_fails:
            lines.append("- ✅ 失败列表与基线完全一致（无新增、无修复）")
    else:
        lines.append("- ℹ️ 无基线对比（首次运行或基线文件不存在）")
    lines.append("")

    # 结论 checklist
    lines.append("### 结论")
    lines.append("")
    current_fails = {c["name"] for c in data["failed_cases"]}
    new_fails = current_fails - baseline_fails if baseline_fails else set()

    if not new_fails:
        lines.append("- [x] 无新增失败（符合基线预期）")
    else:
        lines.append("- [ ] 存在新增失败，需修复或明示为预期影响")

    if baseline_fails and (baseline_fails - current_fails):
        lines.append("- [x] 基线失败已部分修复")
    else:
        lines.append("- [ ] 未修复历史失败（可选）")

    lines.append(f"- [x] 本次测试完成（共 {total} 用例）")
    lines.append("")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Convert pytest JUnit XML to Markdown report")
    parser.add_argument("xml", nargs="?", default="logs/pytest-latest.xml", help="JUnit XML path")
    parser.add_argument("--baseline-xml", default="logs/pytest-baseline.xml", help="Baseline XML for comparison")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    args = parser.parse_args()

    if not Path(args.xml).exists():
        print(f"Error: XML file not found: {args.xml}", file=sys.stderr)
        sys.exit(1)

    data = parse_junit(args.xml)
    baseline_data = None
    if args.baseline_xml and Path(args.baseline_xml).exists():
        baseline_data = parse_junit(args.baseline_xml)

    report = generate_report(data, baseline_data)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
