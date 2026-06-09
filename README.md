# Mining Intelligence Aggregator

一个矿业新闻、关键矿产政策、价格信息三源聚合管线。项目包含采集、清洗、去重、入库、自然语言查询接口，以及基础评测脚本。

## 目录

- `pipeline/`: 采集、清洗、去重、向量入库和检索逻辑
- `serve/`: FastAPI `/query` REST 接口
- `eval/`: 20 条 ground truth Q&A 和自动评测脚本
- `DATA_NOTES.md`: schema、字段、主键、去重策略说明

## 快速开始

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pipeline.run --days 30 --limit-per-source 200
uvicorn serve.app:app --reload
```

查询示例:

```powershell
$body = @{ question = '近 7 天澳洲锂出口政策有何变化?'; top_k = 5 } | ConvertTo-Json -Compress
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/query `
  -ContentType 'application/json; charset=utf-8' `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

运行评测:

```powershell
python -m eval.run_eval
```
