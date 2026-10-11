import pytest
import os
from app.analyzers.api_python import PythonAPIAnalyzer
from app.analyzers.api_express import ExpressAPIAnalyzer
from app.analyzers.api_spring import SpringAPIAnalyzer
from app.models.schemas import Endpoint

def test_fastapi_endpoint_detection(tmp_path):
    repo_dir = tmp_path / "fastapi_app"
    repo_dir.mkdir()

    # File with router prefix
    router_file = repo_dir / "router.py"
    router_file.write_text("from fastapi import APIRouter\nuser_router = APIRouter(prefix='/users')\n@user_router.get('/profile')\ndef get_profile(): pass")

    # File with app
    app_file = repo_dir / "main.py"
    app_file.write_text("from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): pass")

    analyzer = PythonAPIAnalyzer(str(repo_dir))
    endpoints = analyzer.analyze(["router.py", "main.py"])

    paths = [e.path for e in endpoints]
    assert "/users/profile" in paths
    assert "/health" in paths

def test_express_endpoint_detection(tmp_path):
    repo_dir = tmp_path / "express_app"
    repo_dir.mkdir()

    # Router with prefix
    router_file = repo_dir / "users.js"
    router_file.write_text("const express = require('express');\nconst userRouter = express.Router();\nuserRouter.get('/profile', (req, res) => {});")

    # App using router
    app_file = repo_dir / "app.js"
    app_file.write_text("const express = require('express');\nconst app = express();\nconst userRouter = require('./users');\napp.use('/users', userRouter);")

    analyzer = ExpressAPIAnalyzer(str(repo_dir))
    endpoints = analyzer.analyze(["users.js", "app.js"])

    paths = [e.path for e in endpoints]
    assert "/users/profile" in paths

def test_spring_endpoint_detection(tmp_path):
    repo_dir = tmp_path / "spring_app"
    repo_dir.mkdir()

    # Controller with class prefix
    ctrl_file = repo_dir / "UserController.java"
    ctrl_file.write_text("@RequestMapping(\"/api/users\")\npublic class UserController {\n    @GetMapping(\"/profile\")\n    public String getProfile() { return \"ok\"; }\n}")

    analyzer = SpringAPIAnalyzer(str(repo_dir))
    endpoints = analyzer.analyze(["UserController.java"])

    paths = [e.path for e in endpoints]
    assert "/api/users/profile" in paths
