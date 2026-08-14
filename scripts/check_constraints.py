"""项目硬约束门禁脚本：交付前检查业务目录代码结构约束。

约束规则（见项目 .claude/CLAUDE.md 代码结构化）：
1. 每个 .py 文件不超过约 200 行，超出拆分为多个文件（违规 → 门禁失败）。
2. 模块级公开函数不超过 5 个，超出拆分（违规 → 门禁失败）。
3. 类公开方法超过阈值（默认 8）仅警告：数据访问/接口类（如 GradeStore 十方法）
   属可接受例外，人工确认即可，不阻断交付。

扫描范围默认 app/、services/、utils/（业务代码，tests/ 用例文件不计入函数约束），
可在命令行用 --dirs 覆盖。退出码：0=通过（警告不影响），1=存在硬约束违规。

用法：
    python scripts/check_constraints.py
    python scripts/check_constraints.py --dirs app services
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# 默认扫描的业务目录（相对项目根）
_DEFAULT_DIRS = ("app", "services", "utils")


def _is_public(name: str) -> bool:
    """是否公开符号：不以单下划线开头。"""
    return not name.startswith("_")


def _module_public_funcs(tree: ast.Module) -> int:
    """模块级公开函数计数：顶层 def/async def，不在类内、不以 _ 开头。"""
    return sum(
        1
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _is_public(node.name)
    )


def _class_public_methods(tree: ast.Module) -> dict[str, int]:
    """按类统计公开方法数，返回 {类名: 方法数}。"""
    counts: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            counts[node.name] = sum(
                1
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _is_public(child.name)
            )
    return counts


def check_file(path: Path, max_lines: int, max_funcs: int, class_warn: int) -> list[str]:
    """检查单个文件，返回违规描述列表，空列表表示通过。

    返回项以 "类 " 开头的是警告（不阻断），其余为硬约束失败。
    """
    violations: list[str] = []
    source = path.read_text(encoding="utf-8")
    if len(source.splitlines()) > max_lines:
        violations.append(f"行数 {len(source.splitlines())} > {max_lines}")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        violations.append(f"语法错误: {exc}")
        return violations
    funcs = _module_public_funcs(tree)
    if funcs > max_funcs:
        violations.append(f"模块级公开函数 {funcs} 个 > {max_funcs}")
    for class_name, count in _class_public_methods(tree).items():
        if count > class_warn:
            violations.append(
                f"类 {class_name} 公开方法 {count} 个（>{class_warn}，"
                "数据访问/接口类可接受，否则考虑拆分）"
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dirs",
        nargs="+",
        default=list(_DEFAULT_DIRS),
        help="扫描的业务目录，默认 app services utils",
    )
    parser.add_argument("--max-lines", type=int, default=200, help="单文件行数上限")
    parser.add_argument("--max-funcs", type=int, default=5, help="模块级公开函数上限")
    parser.add_argument(
        "--class-warn",
        type=int,
        default=8,
        help="类公开方法超过该数仅警告，不阻断",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    files = sorted(p for d in args.dirs for p in (root / d).rglob("*.py"))
    if not files:
        print("未找到任何 .py 文件，请确认扫描目录存在", file=sys.stderr)
        return 1

    hard_fail = False
    for path in files:
        violations = check_file(path, args.max_lines, args.max_funcs, args.class_warn)
        if not violations:
            continue
        rel = path.relative_to(root)
        for violation in violations:
            if violation.startswith("类 "):
                print(f"[WARN] {rel}: {violation}")
            else:
                print(f"[FAIL] {rel}: {violation}")
                hard_fail = True
    if hard_fail:
        print("约束门禁未通过：存在硬约束违规，先拆分重构再交付", file=sys.stderr)
        return 1
    print("约束门禁通过（警告需人工确认，不阻断交付）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
