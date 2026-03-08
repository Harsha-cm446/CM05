# 🎯 AI-Based Realistic HR Interview Simulator & Recruitment Platform

A production-ready web platform for AI-powered interview practice and corporate recruitment. Students practice with adaptive AI interviews; companies conduct real interviews with live video, bulk invitations, and automatic AI evaluation.

**100% Free & Open-Source** — No paid APIs required.

---

## 🏗 Tech Stack

| Layer        | Technology                                      |
| ------------ | ----------------------------------------------- |
| Frontend     | React 18 (Vite), TailwindCSS, WebRTC, Recharts  |
| Backend      | Python 3.11+, FastAPI, Uvicorn, WebSockets       |
| Database     | MongoDB (Motor async driver)                     |
| Auth         | JWT (python-jose), bcrypt                        |
| AI / LLM     | Google Gemini (gemini-2.5-flash) with multi-key fallback |
| NLP          | SentenceTransformers (all-MiniLM-L6-v2)         |
| Speech       | OpenAI Whisper (open-source, local)              |
| Vision       | OpenCV + DeepFace (emotion/confidence detection) |
| Email        | aiosmtplib (Gmail SMTP)                          |
| PDF          | fpdf2                                            |
| Deployment   | Docker Compose / Render (all free)                |

---

## 📁 Project Structure

```
ai-interview-platform/
├── backend/
│   ├── app/
│   │   ├── core/          # Config, DB, Security (JWT)
│   │   ├── models/        # Pydantic schemas
│   │   ├── routers/       # API routes + WebSocket
│   │   ├── services/      # AI, Email, PDF services
│   │   └── utils/
│   ├── main.py            # FastAPI app entry
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/    # Navbar
│   │   ├── context/       # AuthContext
│   │   ├── pages/         # All page components
│   │   └── services/      # API client (axios)
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
├── ai-engine/
│   ├── video_analysis.py  # DeepFace emotion detection
│   ├── speech_to_text.py  # Whisper transcription
│   └── requirements.txt
├── docker-compose.yml
└── README.md
```

---

## 🚀 Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- Node.js 18+
- MongoDB (local or Atlas free tier)
- Google Gemini API key — https://aistudio.google.com/apikey

### 1. Clone & Setup Backend

```bash
cd backend
cp .env.example .env      # Edit with your settings
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Start MongoDB
```bash
# Option A: Local
mongod

# Option B: Docker
docker run -d -p 27017:27017 --name mongo mongo:7
```

### 3. Set Gemini API Keys
Add your Gemini API keys to the `.env` file:
```
GEMINI_API_KEY=your-primary-gemini-api-key
GEMINI_FALLBACK_API_KEYS=second-key,third-key
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=gemini-3-flash-preview,gemini-3.1-flash-lite-preview,gemini-2.5-flash-lite,gemini-3.1-pro-preview,gemini-2.5-pro
```

### 4. Run Backend
```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 5. Setup & Run Frontend
```bash
cd frontend
npm install
npm run dev               # Starts on http://localhost:5173
```

### 6. Open the App
Visit **http://localhost:5173**

---

## 🐳 Docker Compose (Full Stack)

```bash
# Start everything
docker compose up -d

# Frontend still runs separately:
cd frontend && npm install && npm run dev
```

---

## 🔑 Core Features

### 1. 🎓 Student Mock Interview
- Select role & difficulty → AI generates dynamic questions
- Answer via text (voice recording support included)
- Camera feed for emotion/confidence analysis
- Adaptive difficulty (increases/decreases based on performance)
- Downloadable PDF performance report with charts

### 2. 🏢 HR Live Interview Mode
- Create interview sessions with job role, schedule, duration
- Upload/enter candidate emails for bulk invitations
- Each candidate receives a unique token-based link
- Real-time video grid view (WebRTC)
- HR can mute, remove candidates, send chat messages
- End interview for all participants

### 3. 📧 Bulk Email Invitations
- Auto-generates unique `https://domain.com/interview/{token}` links
- Sends styled HTML emails via SMTP
- Tracks candidate status (invited → joined → completed)

### 4. 📊 AI Evaluation Engine
| Metric             | Weight | Method                           |
| ------------------- | ------ | -------------------------------- |
| Content Score       | 40%    | Semantic similarity + keywords   |
| Communication       | 30%    | Response length & structure      |
| Confidence          | 20%    | DeepFace emotion analysis        |
| Emotion Stability   | 10%    | Emotion variance measurement     |

### 5. 📄 PDF Report Generation
- Overall scores with color coding
- Radar chart (skills) + bar chart (per-question)
- Strengths, weaknesses, improvement suggestions
- Question-wise breakdown with ideal answers

---

## 🗄 Database Schema

### Users
`name`, `email`, `password` (hashed), `role` (student/hr/admin), `created_at`

### InterviewSessions
`job_role`, `scheduled_time`, `duration_minutes`, `company_name`, `session_token`, `status`, `created_by`, `candidate_count`

### Candidates
`email`, `interview_session_id`, `unique_token`, `status`, `invited_at`, `joined_at`

### MockSessions
`user_id`, `job_role`, `difficulty`, `questions[]`, `responses[]`, `status`, `current_question_index`

---

## 🔒 Security
- JWT authentication with role-based access control
- Password hashing (bcrypt)
- Token-based interview link access with validation
- CORS configured for frontend origin only

---

## 📧 Email Setup (Gmail SMTP)

1. Enable 2-Factor Auth on your Gmail
2. Go to Google Account → Security → App Passwords
3. Generate an app password for "Mail"
4. Set in `.env`:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=your-email@gmail.com
```

---

## 🌐 Free Deployment (Render)

| Component   | Free Service          |
| ----------- | --------------------- |
| Frontend    | Render (render.com)   |
| Backend     | Render (render.com)   |
| Database    | MongoDB Atlas Free    |
| AI/LLM      | Google Gemini API (free tier available) |

### Deploy to Render
1. Push to GitHub
2. Go to [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**
3. Connect your repo → Render reads `render.yaml` and creates both services
4. Set these environment variables:
   - **Backend**: `MONGODB_URL` (Atlas connection string), `GEMINI_API_KEY`, `GEMINI_FALLBACK_API_KEYS`, `FRONTEND_URL`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`
   - **Frontend**: `VITE_API_URL` (e.g. `https://ai-interview-backend.onrender.com/api`), `VITE_WS_URL` (e.g. `wss://ai-interview-backend.onrender.com`)

---

## 🧪 API Endpoints

### Auth
- `POST /api/auth/register` — Create account
- `POST /api/auth/login` — Login

### Mock Interview (Student)
- `POST /api/mock-interview/start` — Start mock session
- `POST /api/mock-interview/{id}/answer` — Submit answer
- `GET /api/mock-interview/{id}/report` — Get report JSON
- `GET /api/mock-interview/{id}/report/pdf` — Download PDF
- `GET /api/mock-interview/history/me` — Interview history

### HR Interviews
- `POST /api/interviews/sessions` — Create session
- `GET /api/interviews/sessions` — List sessions
- `POST /api/interviews/sessions/{id}/invite` — Invite candidates
- `GET /api/interviews/sessions/{id}/candidates` — List candidates
- `DELETE /api/interviews/sessions/{id}` — Delete session

### WebSocket
- `WS /ws/interview/{room_id}` — Real-time interview room

---

## License

MIT — Free for academic and commercial use.
