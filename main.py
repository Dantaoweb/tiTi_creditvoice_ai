from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "CrediVoice TiTi is live 🚀"}
