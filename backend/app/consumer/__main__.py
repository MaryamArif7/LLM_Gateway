import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.consumer.main:app", host="0.0.0.0", port=int(os.environ.get("CONSUMER_PORT", "8001")))
