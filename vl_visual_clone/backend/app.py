from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from pipeline import run_pipeline
from schemas import RunRequest, RunResponse

app = FastAPI(title="VL Visual Clone", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/run", response_model=RunResponse)
def run(req: RunRequest):
    input_pdf = Path(req.inputPdf).expanduser().resolve()
    if not input_pdf.exists():
        raise HTTPException(status_code=400, detail=f"Input PDF not found: {input_pdf}")

    output_dir = Path(req.outputDir).expanduser().resolve()
    try:
        result = run_pipeline(
            input_pdf=input_pdf,
            output_dir=output_dir,
            api_base=req.apiBase,
            source_lang=req.sourceLang,
            target_lang=req.targetLang,
            enable_translate=req.enableTranslate,
            geometry_source=req.geometrySource,
            render_background=req.renderBackground,
            ocr_engine=req.ocrEngine,
            compare_all_engines=req.compareAllEngines,
            mineru_api_base=req.mineruApiBase,
            dotsocr_api_base=req.dotsocrApiBase,
            dotsocr_model=req.dotsocrModel,
            dotsocr_prompt=req.dotsocrPrompt,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))

    return RunResponse(
        ok=True,
        message="Pipeline completed",
        jsonPath=result["jsonPath"],
        translatedJsonPath=result["translatedJsonPath"],
        outputPdfPath=result["outputPdfPath"],
        stats=result["stats"],
        runs=result.get("runs"),
    )


@app.get("/api/file")
def get_file(path: str = Query(...)):
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(p))
