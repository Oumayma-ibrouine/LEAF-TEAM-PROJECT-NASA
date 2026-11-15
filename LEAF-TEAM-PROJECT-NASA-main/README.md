# LEAF TEAM — NASA project

Crop suitability analysis for a field (climate NASA POWER / GPM, soil FAO GAEZ v5),
crop rotation proposals, PDF report, and AI plant photo inspection.

## Run locally

```bash
cd back-end
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # then paste your free Gemini key in .env
python download_gaez.py           # downloads FAO GAEZ rasters (~1.4 GB, not in git)
uvicorn main:app --port 8000 --reload
```

Front end: serve `front end leaf team/` (e.g. `python -m http.server 5500 --directory "front end leaf team"`)
and open http://localhost:5500.

## Configuration (`back-end/.env`, never committed)

| Variable | Use |
|---|---|
| `GEMINI_API_KEY` | Plant photo analysis (free key: https://aistudio.google.com/apikey) |
| `ANTHROPIC_API_KEY` | Optional: Claude instead of Gemini (`IA_FOURNISSEUR=claude`) |
| `EE_PROJECT` | Optional: GPM rainfall via Google Earth Engine (falls back to NASA POWER) |
