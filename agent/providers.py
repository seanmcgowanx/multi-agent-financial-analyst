"""Handle HTTP errors and bounded Yahoo data access."""

import contextlib
import json
import logging
import math
import subprocess
import sys
import time
from typing import Any, TypeVar

import requests
from pydantic import BaseModel

from agent.config import ROOT, Settings
from agent.schemas import (
    EarningsHistory,
    EarningsRecord,
    FinancialStatements,
    PriceBar,
    PriceHistory,
    StatementPeriod,
    ToolError,
    ToolResult,
)
from agent.schemas import ticker_symbol as ticker_symbol


class ToolFailure(Exception):
    """Carry a safe error from a provider boundary."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        self.error = ToolError(code=code, message=message, retryable=retryable)
        super().__init__(message)


def failure(source: str, error: ToolFailure) -> ToolResult:
    """Build a structured failure without raw exception text."""
    return ToolResult(status="error", source=source, error=error.error)


def invalid(source: str) -> ToolResult:
    """Report invalid tool input."""
    return failure(
        source,
        ToolFailure(
            "invalid_input", "Check the tool input and allowed ranges."
        ),
    )


def bounded_int(value: int, maximum: int) -> bool:
    """Reject booleans, fractions, and values outside the limit."""
    return type(value) is int and 1 <= value <= maximum


def require_key(value: str) -> None:
    """Stop before a request if no key is configured."""
    if not value.strip():
        raise ToolFailure("missing_key", "Set the provider API key locally.")


def request_json(
    method: str,
    url: str,
    settings: Settings,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    body: dict | None = None,
) -> dict[str, Any]:
    """Use finite timeouts and optional retries for temporary failures."""
    for attempt in range(settings.max_retries + 1):
        try:
            with requests.request(
                method,
                url,
                params=params,
                headers=headers,
                json=body,
                timeout=(settings.request_timeout, settings.request_timeout),
                allow_redirects=False,
            ) as response:
                status = response.status_code
                if status in (401, 403):
                    raise ToolFailure(
                        "authentication", "The provider rejected access."
                    )
                if status == 429:
                    raise ToolFailure(
                        "rate_limit",
                        "The provider request limit was reached.",
                        True,
                    )
                if status >= 500:
                    raise ToolFailure(
                        "provider_error", "The provider is unavailable.", True
                    )
                if not 200 <= status < 300:
                    raise ToolFailure(
                        "provider_error", "The provider rejected the request."
                    )
                try:
                    data = response.json()
                except ValueError:
                    raise ToolFailure(
                        "invalid_response",
                        "The provider returned invalid JSON.",
                    ) from None
                if not isinstance(data, dict):
                    raise ToolFailure(
                        "invalid_response", "The provider response is invalid."
                    )
                return data
        except requests.Timeout:
            error = ToolFailure("timeout", "The request timed out.", True)
        except requests.RequestException:
            error = ToolFailure(
                "network_error", "The network request failed.", True
            )
        except ToolFailure as exc:
            error = exc
        if not error.error.retryable or attempt == settings.max_retries:
            raise error from None
        time.sleep(min(2**attempt, 4))
    raise RuntimeError("The request loop ended without a result.")


def bad_response(source: str) -> ToolResult:
    """Reject malformed data without returning raw provider content."""
    return failure(
        source,
        ToolFailure(
            "invalid_response",
            "The provider data did not match the expected format.",
        ),
    )


T = TypeVar("T", bound=BaseModel)


def run_yahoo(
    operation: str,
    ticker: str,
    option: str,
    settings: Settings,
    schema: type[T],
) -> ToolResult[T]:
    """Return typed Yahoo data within the configured time budget."""
    source = "yfinance"
    payload = json.dumps(
        {
            "operation": operation,
            "ticker": ticker,
            "option": option,
            "timeout": settings.request_timeout,
        }
    )
    try:
        process = subprocess.run(
            [sys.executable, "-m", "agent.providers"],
            input=payload,
            text=True,
            capture_output=True,
            cwd=ROOT,
            timeout=settings.yahoo_timeout,
            check=False,
        )
        if process.returncode != 0:
            raise ToolFailure(
                "provider_error", "Yahoo data could not be loaded.", True
            )
        raw = json.loads(process.stdout)
        return ToolResult[schema].model_validate(raw)
    except subprocess.TimeoutExpired:
        return failure(
            source,
            ToolFailure("timeout", "The Yahoo request timed out.", True),
        )
    except OSError:
        return failure(
            source,
            ToolFailure(
                "dependency_missing", "The Yahoo worker could not start."
            ),
        )
    except ToolFailure as exc:
        return failure(source, exc)
    except (ValueError, TypeError):
        return bad_response(source)


def number(value: Any) -> float | None:
    """Convert missing or non-finite values to null."""
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def statement_rows(frame: Any) -> list[StatementPeriod]:
    """Convert a Yahoo statement table to period records."""
    if frame is None or frame.empty:
        return []
    return [
        StatementPeriod(
            period_end=column.date(),
            values={
                str(name): number(value) for name, value in series.items()
            },
        )
        for column, series in frame.items()
    ]


def fetch(payload: dict, ticker_factory: Any) -> ToolResult:
    """Map provider tables to stable tool schemas."""
    symbol = payload["ticker"]
    ticker = ticker_factory(symbol)
    operation = payload["operation"]
    warnings = []
    if operation == "prices":
        frame = ticker.history(
            period=payload["option"],
            interval="1d",
            auto_adjust=False,
            actions=False,
            timeout=payload["timeout"],
            raise_errors=True,
        )
        bars = []
        if frame is not None:
            for index, row in frame.iterrows():
                bars.append(
                    PriceBar(
                        date=index.date(),
                        open=row["Open"],
                        high=row["High"],
                        low=row["Low"],
                        close=row["Close"],
                        volume=row["Volume"],
                    )
                )
        metadata = ticker.history_metadata if bars else {}
        data = PriceHistory(
            ticker=symbol,
            currency=metadata.get("currency"),
            exchange_timezone=metadata.get("exchangeTimezoneName"),
            bars=bars,
        )
        has_data = bool(bars)
    elif operation == "statements":
        frequency = "yearly" if payload["option"] == "annual" else "quarterly"
        income = statement_rows(ticker.get_income_stmt(freq=frequency))
        balance = statement_rows(ticker.get_balance_sheet(freq=frequency))
        cash = statement_rows(ticker.get_cash_flow(freq=frequency))
        data = FinancialStatements(
            ticker=symbol,
            frequency=payload["option"],
            income_statement=income,
            balance_sheet=balance,
            cash_flow=cash,
        )
        has_data = bool(income or balance or cash)
        warnings.append(
            "Reporting currency is not supplied by these statement tables."
        )
        if has_data and not all((income, balance, cash)):
            warnings.append("Some financial statements are unavailable.")
    elif operation == "earnings":
        frame = ticker.get_earnings_history()
        earnings = []
        if frame is not None and not frame.empty:
            for index, row in frame.iterrows():
                earnings.append(
                    EarningsRecord(
                        period=index.date(),
                        eps_estimate=number(row["epsEstimate"]),
                        eps_actual=number(row["epsActual"]),
                        surprise_ratio=number(row["surprisePercent"]),
                    )
                )
        data = EarningsHistory(ticker=symbol, earnings=earnings)
        has_data = bool(earnings)
    else:
        raise ValueError("The Yahoo operation is invalid.")
    if not has_data:
        warnings.append(
            "Yahoo returned no data. "
            "Coverage or provider access may be limited."
        )
    return ToolResult(
        status="ok" if has_data else "empty",
        source="yfinance",
        data=data,
        warnings=warnings,
    )


def main() -> None:
    """Write only safe JSON to standard output."""
    logging.disable(logging.CRITICAL)
    try:
        import yfinance as yf
        from yfinance.exceptions import YFRateLimitError
    except ImportError:
        result = failure(
            "yfinance",
            ToolFailure(
                "dependency_missing", "Install the listed Yahoo dependencies."
            ),
        )
    else:
        try:
            payload = json.loads(sys.stdin.read())
            with contextlib.redirect_stdout(sys.stderr):
                result = fetch(payload, yf.Ticker)
        except YFRateLimitError:
            result = failure(
                "yfinance",
                ToolFailure(
                    "rate_limit", "The Yahoo request limit was reached.", True
                ),
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            result = bad_response("yfinance")
        except Exception:
            # The provider can raise errors from several network libraries.
            result = failure(
                "yfinance",
                ToolFailure(
                    "provider_error", "Yahoo data could not be loaded.", True
                ),
            )
    print(result.model_dump_json())


if __name__ == "__main__":
    main()
