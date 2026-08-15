"""鸭鸭日记本研发流水线 Flow（图工程编排）。

图结构：
  需求规格 → 设计 Crew ─┬─> 后端 Crew ─┐
                        └─> 前端 Crew ─┤ and_ 汇聚
                                       ↓
                                  测试 QA Crew
                                       ↓ @router
                    ┌──────────────通过──┴──不通过────────────┐
                    ↓                                         ↓
                验收 Crew                                回退修复（回到开发）
                    ↓
                交付产物
"""
import os
from pathlib import Path

from crewai.flow.flow import Flow, and_, listen, router, start
from crewai.flow.persistence import persist
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = PROJECT_ROOT / "outputs"


class DeliveryFlowState(BaseModel):
    requirements_doc: str = ""
    design_report: str = ""
    backend_status: str = "pending"
    frontend_status: str = "pending"
    test_report: str = ""
    test_passed: bool = False
    acceptance_verdict: str = ""
    retry_count: int = 0


@persist()
class DeliveryFlow(Flow[DeliveryFlowState]):
    """研发流水线：设计 → 并行开发 → 测试 → 验收/回退。"""

    def _read_requirements(self) -> str:
        spec = PROJECT_ROOT / "docs/superpowers/specs/2026-08-16-duck-diary-design.md"
        if spec.exists():
            return spec.read_text(encoding="utf-8")
        return "需求规格缺失"

    @start()
    def load_requirements(self):
        self.state.requirements_doc = self._read_requirements()
        OUTPUTS.mkdir(exist_ok=True)
        return "需求规格已加载"

    @listen(load_requirements)
    def design_stage(self):
        from crews.design_crew import build_crew
        result = build_crew().kickoff(inputs={"requirements": self.state.requirements_doc})
        self.state.design_report = str(result.raw)
        (OUTPUTS / "design_report.md").write_text(self.state.design_report, encoding="utf-8")
        return "design_done"

    @listen(design_stage)
    def backend_stage(self):
        from crews.backend_crew import build_crew
        build_crew().kickoff(inputs={"requirements": self.state.requirements_doc})
        self.state.backend_status = "done"
        return "backend_done"

    @listen(design_stage)
    def frontend_stage(self):
        from crews.frontend_crew import build_crew
        build_crew().kickoff(inputs={"requirements": self.state.requirements_doc})
        self.state.frontend_status = "done"
        return "frontend_done"

    @listen(and_(backend_stage, frontend_stage))
    def qa_stage(self):
        # 真实运行 pytest（质量闭环的权威判定），再由 QA Crew 产出审查意见
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_api.py", "-q"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        passed = result.returncode == 0
        self.state.test_passed = passed
        report = (result.stdout or "") + (result.stderr or "")
        self.state.test_report = report
        (OUTPUTS / "test_report.md").write_text(
            f"# 测试报告\n\npytest 结果：{'通过' if passed else '失败'}\n\n```\n{report}\n```",
            encoding="utf-8",
        )
        (OUTPUTS / "test_result.txt").write_text("PASS" if passed else "FAIL", encoding="utf-8")
        from crews.qa_crew import build_crew
        build_crew().kickoff(inputs={"requirements": self.state.requirements_doc})
        return "qa_done"

    @router(qa_stage)
    def route_acceptance(self):
        if self.state.test_passed:
            return "pass"
        return "fail"

    @listen("pass")
    def acceptance_stage(self):
        from crews.acceptance_crew import build_crew
        result = build_crew().kickoff(inputs={"requirements": self.state.requirements_doc})
        self.state.acceptance_verdict = str(result.raw)
        (OUTPUTS / "acceptance_report.md").write_text(
            self.state.acceptance_verdict, encoding="utf-8"
        )
        return "accepted"

    @listen("fail")
    def fix_stage(self):
        self.state.retry_count += 1
        (OUTPUTS / "fix_notes.md").write_text(
            f"测试未通过，进入回退修复（第 {self.state.retry_count} 次）。", encoding="utf-8"
        )
        # 回退后回到开发阶段重跑（此处记录并等待人工/自动重跑）
        return "fix_required"
