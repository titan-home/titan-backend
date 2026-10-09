"""Tools of the tasks domain."""

from pydantic import BaseModel, ConfigDict, Field

from titan_api.agent.tool import Tool, ToolContext
from titan_core.domains.audit.models import ActionClass, Domain
from titan_core.domains.tasks import service as tasks_service


class CreateTaskInput(BaseModel):
    """What the model sends to create a task."""

    # Spaces around the title are cut off before the length is checked, so a
    # title of spaces only is refused as empty.
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(
        min_length=1,
        description='What to do, as a short action: "Buy milk".',
    )


def _summary(task: CreateTaskInput) -> str:
    return f"Creating a task: {task.title}"


async def _create(context: ToolContext, task: CreateTaskInput) -> str:
    # NOTE: not idempotent, a retried turn would create the task twice; made
    # safe together with the automatic retry of a stalled turn (decision #32).
    created = await tasks_service.create_task(
        context.session, context.user_id, task.title
    )
    # The id lets the model refer to this task later in the conversation.
    return f"Created task {created.id}: {created.title}"


create_task = Tool(
    name="create_task",
    description=(
        "Add a task to the user's task list. Use it whenever the user wants to"
        ' get something done later, even without saying "task": "I need to buy'
        ' milk", "don\'t let me forget to call mom", "put the car service on my'
        ' list". Create one task per thing to do. Write the title as a short'
        " action, in the language the user wrote in, without dates or times."
    ),
    action_class=ActionClass.WRITE_INTERNAL,
    domain=Domain.TASKS,
    # Undone by moving the task to the trash (decision #109).
    undoable=True,
    input_model=CreateTaskInput,
    summary=_summary,
    run=_create,
)
