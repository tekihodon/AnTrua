import json
import os
from pathlib import Path


def load_config():
    config_path = Path(__file__).parent / "config.json"
    file_config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            file_config = json.load(f)

    vietqr = file_config.get("vietqr", {})
    return {
        "dbUrl": os.getenv("DATABASE_URL", file_config.get("dbUrl")),
        "adminPass": os.getenv("ADMIN_PASS", file_config.get("adminPass")),
        "vietqr": {
            "bankBin": os.getenv("VIETQR_BANK_BIN", vietqr.get("bankBin")),
            "bankName": os.getenv("VIETQR_BANK_NAME", vietqr.get("bankName")),
            "accountNo": os.getenv("VIETQR_ACCOUNT_NO", vietqr.get("accountNo")),
            "accountName": os.getenv("VIETQR_ACCOUNT_NAME", vietqr.get("accountName")),
            "template": os.getenv("VIETQR_TEMPLATE", vietqr.get("template", "print")),
            "link_template": os.getenv(
                "VIETQR_LINK_TEMPLATE",
                vietqr.get(
                    "link_template",
                    "https://img.vietqr.io/image/<BANK_ID>-<ACCOUNT_NO>-<TEMPLATE>.png?amount=<AMOUNT>&addInfo=<DESCRIPTION>&accountName=<ACCOUNT_NAME>",
                ),
            ),
        },
    }


config = load_config()

SUPABASE_URL = config["dbUrl"]
ADMIN_PASS = config["adminPass"]
VIETQR = config["vietqr"]
