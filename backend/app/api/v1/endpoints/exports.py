from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.access import legacy_estimate
from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession
from app.models import AuditLog, BackgroundTask
from app.schemas import ExportCsvRequest
from modules.exports import service as exports
from modules.exports import tasks

router = APIRouter(prefix="/exports", tags=["exports"])
tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


def owned_task(task_id, session, user):
    row = session.get(BackgroundTask, task_id)
    if row is None or (user.role != "admin" and row.user_id != user.id):
        raise HTTPException(404, "Задача не найдена")
    return row


@router.post("", status_code=202)
def request_export(payload: ExportCsvRequest, session: DbSession, user: CurrentUser):
    task = tasks.create(session, user.id, payload)
    session.commit()
    return tasks.public(task)


@tasks_router.get("/{task_id}")
@router.get("/{task_id}")
def task_status(task_id: str, session: DbSession, user: CurrentUser):
    return tasks.public(owned_task(task_id, session, user))


@router.get("/{task_id}/download")
def download_export(task_id: str, session: DbSession, user: CurrentUser):
    task = owned_task(task_id, session, user)
    if task.status != "done":
        raise HTTPException(409, "Экспорт ещё не готов")
    root = Path(get_settings().export_dir).resolve()
    path = Path(task.file_ref).resolve() if task.file_ref else None
    if path is None or not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "Файл экспорта не найден")
    session.add(
        AuditLog(
            user_id=user.id,
            action="export.download",
            object_type="background_task",
            object_id=task.id,
        )
    )
    session.commit()
    return FileResponse(
        path, media_type="text/csv; charset=utf-8", filename=f"export-{task.id}.csv"
    )


@router.post("/csv")
def export_csv(payload: ExportCsvRequest, session: DbSession, user: CurrentUser) -> Response:
    """Экспорт текущей выборки; скачивание пишется в аудит (критерий «Экспорт»)."""
    rows = (exports.companies_rows if payload.module == "companies" else exports.investment_rows)(
        session, payload.filters, limit=5001
    )
    if len(rows) > 5000:
        raise HTTPException(413, "Для выборки более 5000 строк используйте POST /exports")
    content = exports.to_csv(rows, payload.module, payload.mode)

    filename = f"export-{payload.module}-{payload.mode}-{uuid4().hex}.csv"

    session.add(
        AuditLog(
            user_id=user.id,
            action="export.csv",
            object_type=payload.module,
            object_id=str(len(rows)),
        )
    )
    session.commit()
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/proposal")
def export_proposal(estimate_id: int, session: DbSession, user: CurrentUser) -> dict:
    legacy_estimate(session, estimate_id, user)
    exports.build_proposal_docx(session, estimate_id, author_id=user.id)
    session.add(
        AuditLog(
            user_id=user.id,
            action="export.proposal",
            object_type="deal_estimate",
            object_id=str(estimate_id),
        )
    )
    session.commit()
    return {
        "download_url": f"{get_settings().api_prefix}/exports/proposal/{estimate_id}/download",
        "status": "created",
    }


@router.get("/proposal/{estimate_id}/download")
def download_proposal(estimate_id: int, session: DbSession, user: CurrentUser) -> FileResponse:
    from app.models import ProposalExport

    legacy_estimate(session, estimate_id, user)
    path = session.scalar(
        select(ProposalExport.file_ref)
        .where(ProposalExport.deal_estimate_id == estimate_id)
        .order_by(ProposalExport.id.desc())
        .limit(1)
    )
    root = Path(get_settings().export_dir).resolve()
    target = Path(path).resolve() if path else None
    if target is None or not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Файл не найден, сформируйте документ заново"
        )
    session.add(
        AuditLog(
            user_id=user.id,
            action="export.download",
            object_type="deal_estimate",
            object_id=str(estimate_id),
        )
    )
    session.commit()
    return FileResponse(
        path,
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        filename=Path(path).name,
    )
