"""验收 Crew：验收负责人。

产出：对照验收清单逐项核验的验收报告（通过/不通过 + 缺陷清单 + 遗留风险）。
"""
from crewai import Agent, Crew, Process, Task

from config.llm import get_deepseek_llm


def build_crew() -> Crew:
    llm = get_deepseek_llm()

    acceptor = Agent(
        role="验收负责人",
        goal=(
            "对照需求规格与验收清单，逐项核验鸭鸭日记本应用是否达标，"
            "产出结论明确的验收报告（通过/不通过、缺陷清单、遗留风险）"
        ),
        backstory=(
            "你是一名负责最终交付验收的负责人，只认事实与可复现的证据，"
            "不做任何粉饰，明确给出放行或打回的结论。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    accept_task = Task(
        description=(
            "对照以下需求规格，逐项核验鸭鸭日记本应用交付物是否达标，"
            "输出验收报告（逐项结论 + 通过/不通过 + 缺陷清单 + 遗留风险）。\n\n"
            "需求规格：\n{requirements}"
        ),
        expected_output="验收报告（逐项结论 + 通过/不通过 + 缺陷清单 + 遗留风险）。",
        agent=acceptor,
    )

    return Crew(
        agents=[acceptor],
        tasks=[accept_task],
        process=Process.sequential,
        verbose=True,
    )
