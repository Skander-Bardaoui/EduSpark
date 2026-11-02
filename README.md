<p align="center">
  <img src="docs/banner.svg" width="100%" alt="EduSpark banner" />
</p>

<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=22&pause=1200&color=8B5CF6&center=true&vCenter=true&width=760&lines=Learn%2C+teach%2C+create;Django+%2B+PostgreSQL;AI+study+planning" alt="Typing tagline" />
</p>

<p align="center">
  <img src="https://img.shields.io/github/languages/top/Skander-Bardaoui/EduSpark?style=flat-square&color=8B5CF6" alt="" />
  <img src="https://img.shields.io/github/stars/Skander-Bardaoui/EduSpark?style=flat-square&color=8B5CF6" alt="" />
  <img src="https://img.shields.io/github/last-commit/Skander-Bardaoui/EduSpark?style=flat-square&color=C084FC" alt="" />
  <img src="https://img.shields.io/badge/status-Active-8B5CF6?style=flat-square" alt="" />
</p>

## Overview

EduSpark is a multimodal education platform built with Django. Administrators, teachers and students each get a dedicated portal, with role-based access control, a course catalogue, exercises and assessments, exam sessions, forums, progress tracking, dropout-risk monitoring and an AI study-planning assistant.

## Highlights

- Separate admin, teacher and student portals with role-based permissions
- Course catalogue, exercises, assessments, exam sessions and grading
- Discussion forums and learner progress tracking
- Dropout-risk monitoring for teachers and administrators
- AI study-planning assistant powered by a local Ollama model
- Docker Compose stack with Django, PostgreSQL and Ollama

## Tech stack

<p align="center">
  <img src="https://skillicons.dev/icons?i=django,python,postgres,docker,tailwind,git,github&theme=dark&perline=8" alt="Tech stack" />
</p>

## Screenshots

<p align="center">
  <a href="docs/screenshots/landing.webp"><img src="docs/screenshots/landing.webp" width="49%" alt="Landing page" /></a>
  <a href="docs/screenshots/dashboard.webp"><img src="docs/screenshots/dashboard.webp" width="49%" alt="Portal dashboard" /></a>
  <a href="docs/screenshots/courses.webp"><img src="docs/screenshots/courses.webp" width="49%" alt="Courses" /></a>
  <a href="docs/screenshots/management.webp"><img src="docs/screenshots/management.webp" width="49%" alt="Management" /></a>
</p>

## Getting started

**Prerequisites:** Python 3.11+ and PostgreSQL, or Docker Compose for the full stack. The AI assistant uses Ollama with qwen2.5:3b.

```bash
# Docker (recommended)
docker compose up -d
docker compose exec ollama ollama pull qwen2.5:3b

# Local Python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp EduSpark/.env.example EduSpark/.env   # then set SECRET_KEY and DB credentials
cd EduSpark && python manage.py migrate
python manage.py seed_courses
python manage.py runserver
```

## Project structure

```text
EduSpark/       Django project (manage.py lives here)
docs/           architecture and coaching scenarios
stitch/         design assets
docker-compose.yml
```

## Documentation

- [Original project documentation](docs/README_ORIGINAL.md)

---

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:8B5CF6,100:0A0A0C&height=110&section=footer" alt="footer" width="100%" />
</p>

<p align="center">
  Built by <a href="https://github.com/Skander-Bardaoui"><b>Skander Bardaoui</b></a> ·
  <a href="https://skander-bardaoui.netlify.app/">Portfolio</a> ·
  <a href="https://github.com/Skander-Bardaoui?tab=repositories">All repositories</a>
</p>
