import logging
import json
import traceback
import azure.functions as func

try:
    from main1 import run
except Exception as e:
    logging.error("Failed to import main1.run(): %s\n%s", e, traceback.format_exc())
    raise


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("StockAnalysisHttp triggered")
    try:
        # Parse tickers from query string or POST body
        tickers = None
        fmt = "html"

        # Query params
        tickers_param = req.params.get("tickers")
        fmt = req.params.get("format", "html").lower()

        if tickers_param:
            tickers = [t.strip().upper() for t in tickers_param.split(",") if t.strip()]

        # POST body override
        if not tickers:
            try:
                body = req.get_json()
                if isinstance(body, dict):
                    tickers = body.get("tickers")
                    fmt = body.get("format", fmt)
                    if isinstance(tickers, str):
                        tickers = [t.strip().upper() for t in tickers.split(",") if t.strip()]
            except ValueError:
                pass

        if not tickers:
            return func.HttpResponse(
                json.dumps({"error": "No tickers provided. Use ?tickers=AAPL,MSFT or POST {\"tickers\": [\"AAPL\"]}"}),
                status_code=400,
                mimetype="application/json",
            )

        # Run analysis (no email)
        result = run(tickers=tickers, send_email_flag=False, output_format=fmt)

        if fmt == "json":
            return func.HttpResponse(
                json.dumps(result, default=str),
                mimetype="application/json",
            )
        else:
            return func.HttpResponse(
                result or "<html><body><p>No report generated</p></body></html>",
                mimetype="text/html",
            )

    except Exception as e:
        logging.error("StockAnalysisHttp error: %s\n%s", e, traceback.format_exc())
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
