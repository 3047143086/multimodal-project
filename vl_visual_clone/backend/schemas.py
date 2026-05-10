from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    inputPdf: str = Field(..., description="Input PDF path")
    outputDir: str = Field("/u01/huzekun/data/FUNSD/test", description="Output directory")
    apiBase: str = Field("http://127.0.0.1:8080", description="PaddleOCR-VL API base")
    sourceLang: str = Field("zh", description="Source language")
    targetLang: str = Field("en", description="Target language")
    enableTranslate: bool = Field(True, description="Enable translation")
    geometrySource: str = Field("auto", description="auto, parsing or layout-hybrid")
    renderBackground: bool = Field(True, description="Render page background image")
    ocrEngine: str = Field("paddleocr-vl", description="paddleocr-vl, mineru, dotsocr")
    compareAllEngines: bool = Field(False, description="Run and compare all engines in one request")
    mineruApiBase: str = Field("http://127.0.0.1:18000", description="MinerU API base URL")
    dotsocrApiBase: str = Field("http://127.0.0.1:18001", description="DotsOCR API base URL")
    dotsocrModel: str = Field("model", description="DotsOCR model name")
    dotsocrPrompt: str = Field("", description="Optional prompt for DotsOCR parser")


class RunResponse(BaseModel):
    ok: bool
    message: str
    jsonPath: str
    translatedJsonPath: str
    outputPdfPath: str
    stats: dict
    runs: list[dict] | None = None
