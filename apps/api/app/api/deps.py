from app.application.experiments import DeepAgentsExperimentService
from functools import lru_cache

from app.audit.logger import AuditService, EventBroker
from app.core.settings import Settings, get_settings
from app.infrastructure.deepagents import DeepAgentsRunner
from app.files.parser import DocumentParser
from app.llm.deepseek_client import DeepSeekClient
from app.services.course_agent import CourseAgentService
from app.services.decision_model import DecisionModelService
from app.storage.thread_store import ThreadStore
from app.workflows.course_graph import CourseGraph


@lru_cache
def get_service() -> CourseAgentService:
    settings: Settings = get_settings()
    broker = EventBroker()
    store = ThreadStore(settings.database_url)
    audit = AuditService(broker, store=store)
    parser = DocumentParser()
    graph = CourseGraph(
        settings=settings,
        store=store,
        broker=broker,
        audit=audit,
        deepseek=DeepSeekClient(settings),
    )
    return CourseAgentService(
        settings=settings,
        store=store,
        broker=broker,
        audit=audit,
        parser=parser,
        graph=graph,
    )


@lru_cache
def get_decision_model_service() -> DecisionModelService:
    settings: Settings = get_settings()
    return DecisionModelService(settings)


@lru_cache
def get_deepagents_service() -> DeepAgentsExperimentService:
    service = get_service()
    settings = get_settings()
    return DeepAgentsExperimentService(
        runner=DeepAgentsRunner(
            store=service.store,
            llm=service.graph.deepseek,
            enabled=settings.deepagents_experiment_enabled,
        )
    )
