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
            "按 API 契约与数据模型，实现 FastAPI + SQLAlchemy + SQLite 后端："
            "幼儿/小鸭/排班/会话/流水/情绪/评估/小鸭档案的 CRUD 与业务接口"
        ),
        backstory=(
            "你是一名严谨的后端工程师，精通 FastAPI 与 SQLAlchemy 2.0，"
            "重视数据完整性、接口契约一致性与错误处理。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    ai_engineer = Agent(
        role="AI 引擎工程师",
        goal=(
            "实现对话引擎（「鸭鸭日记本」角色、轮次控制、提前终止、历史感知）、"
            "信息提炼、多维能力评估（打分+理由）与小鸭档案汇总，"
            "全部走 LLM 结构化 JSON 输出"
        ),
        backstory=(
            "你是一名 LLM 应用工程师，擅长设计 system prompt 与 JSON schema，"
            "让模型稳定输出可落库的结构化结果。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    backend_task = Task(
        description=(
            "实现后端数据层与 API：定义 SQLAlchemy 模型（children/ducks/duty_rosters/"
            "conversations/messages/feeding_logs/emotion_logs/assessment_dimensions/"
            "assessments/assessment_scores/duck_archives），并提供 CRUD 与排班、"
            "分析（成长曲线）接口。"
        ),
        expected_output="可运行的 FastAPI 后端代码与数据模型。",
        agent=backend,
    )

    ai_task = Task(
        description=(
            "实现 AI 引擎：对话引擎（角色=鸭鸭日记本，一问一答算 1 轮，默认最大 3 轮，"
            "信息充分可提前终止，注入幼儿档案+近期摘要+小鸭档案）、信息提炼（饲养流水/"
            "情绪/心得）、多维评估（1-5 分 + 评分理由）、小鸭档案汇总。"
        ),
        expected_output="AI 引擎服务代码（LLM 结构化输出 + prompt 模板）。",
        agent=ai_engineer, context=[backend_task],
    )

    return Crew(
        agents=[backend, ai_engineer],
        tasks=[backend_task, ai_task],
        process=Process.sequential,
        verbose=True,
    )
