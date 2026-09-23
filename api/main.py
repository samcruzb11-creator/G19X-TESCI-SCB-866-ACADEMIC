from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def inicio():
    return {
        "mensaje": "Sistema de Trazabilidad Documental",
        "estado": "API funcionando correctamente"
    }