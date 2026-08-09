from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import storage
from app.api.deps import read_access, write_access
from app.api.jobs import get_job_or_404
from app.config import get_settings
from app.database import get_db
from app.models import JobDocument

router = APIRouter(tags=["documents"])

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class DocumentRegister(BaseModel):
    """Attach an existing file (e.g. on the OneDrive share) to a job by path."""

    file_path: str = Field(min_length=1, max_length=1000)
    doc_type: str = Field(default="document", max_length=32)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    filename: str
    doc_type: str
    added_at: datetime


@router.get(
    "/jobs/{job_id}/documents",
    response_model=list[DocumentOut],
    dependencies=[Depends(read_access)],
)
def list_documents(job_id: int, db: Session = Depends(get_db)):
    get_job_or_404(job_id, db)
    return (
        db.query(JobDocument)
        .filter(JobDocument.job_id == job_id)
        .order_by(JobDocument.doc_type, JobDocument.filename)
        .all()
    )


@router.post(
    "/jobs/{job_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def register_document(job_id: int, payload: DocumentRegister, db: Session = Depends(get_db)):
    get_job_or_404(job_id, db)
    path = Path(payload.file_path)
    # Accept the file if it's on disk (dev/on-prem) or already uploaded to R2 (cloud).
    if not path.is_file() and not storage.object_exists(storage.document_key(str(path)), get_settings()):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {path}")
    doc = JobDocument(
        job_id=job_id,
        filename=path.name,
        doc_type=payload.doc_type,
        file_path=str(path),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/documents/{doc_id}/file", dependencies=[Depends(read_access)])
def open_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(JobDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    path = Path(doc.file_path)
    media_type = MEDIA_TYPES.get(Path(doc.filename).suffix.lower(), "application/octet-stream")

    # Local file present (dev / on-prem) — serve it directly.
    if path.is_file():
        return FileResponse(
            path, media_type=media_type, content_disposition_type="inline", filename=path.name
        )

    # In the cloud the local path won't resolve — stream from R2 (uploader pushed it).
    obj = storage.stream_document(storage.document_key(doc.file_path), get_settings())
    if obj is not None:
        return StreamingResponse(
            obj["Body"],
            media_type=obj.get("ContentType") or media_type,
            headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="File not available (moved, OneDrive not synced, or not yet uploaded to storage).",
    )


@router.delete(
    "/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(write_access)],
)
def remove_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(JobDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    db.delete(doc)  # registration only — never touches the file on disk
    db.commit()
