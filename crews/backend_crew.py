"""后端 Crew：后端工程师 → AI 引擎工程师。

产出：FastAPI + SQLite 数据层与 REST API 实现，以及对话/提炼/评估 AI 引擎实现。
"""
from crewai import Agent, Crew, Process, Task

from config.llm import get_deepseek_llm


def build_crew() -> Crew:
    llm = get_deepseek_llm()

    backend = Agent(
        role="后端工程师",
        goal=(
            "产出后端实现方案说明：FastAPI + SQLAlchemy + SQLite 的模块划分、"
            "数据模型、REST API、关键业务逻辑（排班/审阅/成长曲线）"
        ),
        backstory=(
            "你是一名严谨的后端工程师，精通 FastAPI 与 SQLAlchemy 2.0，"
            "重视数据完整性、接口契约一致性与错误处理。"
            "你只输出实现方案文字，不直接写文件。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    ai_engineer = Agent(
        role="AI 引擎工程师",
        goal=(
            "产出 AI 引擎实现方案说明：对话引擎（鸭鸭日记本角色、轮次控制、"
            "提前终止、历史感知）、信息提炼、多维评估（打分+理由）、小鸭档案汇总"
        ),
        backstory=(
            "你是一名 LLM 应用工程师，擅长设计 system prompt 与 JSON schema，"
            "让模型稳定输出可落库的结构化结果。你只输出方案文字，不直接写文件。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    backend_task = Task(
        description=(
            "产出后端实现方案说明（文字）：SQLAlchemy 模型清单（children/ducks/"
            "duty_rosters/conversations/messages/feeding_logs/emotion_logs/"
            "assessment_dimensions/assessments/assessment_scores/duck_archives）、"
            "REST API 列表、排班与成长曲线分析的业务逻辑。"
        ),
        expected_output="后端实现方案说明（Markdown 文字）。",
        agent=backend,
    )

    ai_task = Task(
        description=(
            "产出 AI 引擎实现方案说明（文字）：对话引擎（角色=鸭鸭日记本，一问一答算 1 轮，"
            "默认最大 3 轮，信息充分可提前终止，注入幼儿档案+近期摘要+小鸭档案）、"
            "信息提炼（饲养流水/情绪/心得）、多维评估（1-5 分+评分理由）、小鸭档案汇总。"
        ),
        expected_output="AI 引擎实现方案说明（Markdown 文字）。",
        agent=ai_engineer, context=[backend_task],
    )

    return Crew(
        agents=[backend, ai_engineer],
        tasks=[backend_task, ai_task],
        process=Process.sequential,
        verbose=True,
    )
