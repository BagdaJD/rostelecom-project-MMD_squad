from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession
from app.models import AuditLog, DealEstimate
from app.schemas import ExportCsvRequest
from modules.exports import service as exports

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("/csv")
def export_csv(payload: ExportCsvRequest, session: DbSession, user: CurrentUser) -> FileResponse:
    """Экспорт текущей выборки; скачивание пишется в аудит (критерий «Экспорт»)."""
    if payload.module != "companies":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неподдерживаемый модуль экспорта")
    rows = exports.companies_rows(session, payload.filters)
    content = exports.to_csv(rows, payload.module, payload.mode)

    from app.core.config import get_settings

    out_dir = Path(get_settings().export_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"export-{payload.module}-{payload.mode}.csv"
    path.write_bytes(content)

    session.add(
        AuditLog(user_id=user.id, action="export.csv", object_type=payload.module,
                 object_id=str(len(rows)))
    )
    session.commit()
    return FileResponse(path, media_type="text/csv", filename=path.name)


@router.post("/proposal")
def export_proposal(estimate_id: int, session: DbSession, user: CurrentUser) -> dict:
    path = exports.build_proposal_docx(session, estimate_id, author_id=user.id)
    session.add(AuditLog(user_id=user.id, action="export.proposal", object_type="deal_estimate",
                         object_id=str(estimate_id)))
    session.commit()
    return {"file_ref": path, "status": "created"}


@router.get("/proposal/{estimate_id}/download")
def download_proposal(estimate_id: int, session: DbSession, user: CurrentUser) -> FileResponse:
    from app.models import ProposalExport

    path = session.scalar(
        select(ProposalExport.file_ref)
        .where(ProposalExport.deal_estimate_id == estimate_id)
        .order_by(ProposalExport.id.desc())
        .limit(1)
    )
    if not path or not Path(path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден, сформируйте документ заново")
    session.add(AuditLog(user_id=user.id, action="export.download", object_type="deal_estimate",
                         object_id=str(estimate_id)))
    session.commit()
    return FileResponse(path, media_type=(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        filename=Path(path).name)
