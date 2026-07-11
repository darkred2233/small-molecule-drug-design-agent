"""
Files API路由 - 文件管理
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from medagent.db.session import get_db

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传文件"""
    try:
        # 读取文件内容
        content = await file.read()

        # 保存文件（简化实现）
        from pathlib import Path

        upload_dir = Path("./.local/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)

        file_path = upload_dir / file.filename
        with open(file_path, "wb") as f:
            f.write(content)

        return {
            "filename": file.filename,
            "size": len(content),
            "path": str(file_path),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
def list_files(
    db: Session = Depends(get_db),
):
    """列出上传的文件"""
    from pathlib import Path

    upload_dir = Path("./.local/uploads")

    if not upload_dir.exists():
        return []

    files = []
    for file_path in upload_dir.iterdir():
        if file_path.is_file():
            files.append({
                "filename": file_path.name,
                "size": file_path.stat().st_size,
                "modified": file_path.stat().st_mtime,
            })

    return files
