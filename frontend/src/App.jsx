import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { AuthProvider, useAuth } from './context/AuthContext';

import Navbar from './components/Navbar';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Register from './pages/Register';
import StudentDashboard from './pages/StudentDashboard';
import MockInterview from './pages/MockInterview';
import InterviewReport from './pages/InterviewReport';
import HRDashboard from './pages/HRDashboard';
import HRAnalytics from './pages/HRAnalytics';
import CandidateComparison from './pages/CandidateComparison';
import CreateSession from './pages/CreateSession';
import SessionDetail from './pages/SessionDetail';
import LiveInterview from './pages/LiveInterview';
import CandidateJoin from './pages/CandidateJoin';
import ProfilePage from './pages/ProfilePage';
import DataCollectionPage from './pages/DataCollectionPage';
import LiveKitMonitorDashboard from './pages/LiveKitMonitorDashboard';

function ProtectedRoute({ children, roles }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex items-center justify-center h-screen">Loading...</div>;
  if (!user) return <Navigate to="/login" />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" />;
  return children;
}

function AppRoutes() {
  const { user } = useAuth();

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100/50">
      <Navbar />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={user ? <Navigate to={user.role === 'hr' ? '/hr' : '/dashboard'} /> : <Login />} />
        <Route path="/register" element={user ? <Navigate to={user.role === 'hr' ? '/hr' : '/dashboard'} /> : <Register />} />

        {/* Student routes */}
        <Route path="/dashboard" element={<ProtectedRoute roles={['student']}><StudentDashboard /></ProtectedRoute>} />
        <Route path="/mock-interview" element={<ProtectedRoute roles={['student']}><MockInterview /></ProtectedRoute>} />
        <Route path="/profile-builder" element={<ProtectedRoute roles={['student']}><DataCollectionPage /></ProtectedRoute>} />
        <Route path="/report/:sessionId" element={<ProtectedRoute roles={['student']}><InterviewReport /></ProtectedRoute>} />

        {/* Profile (all logged-in users) */}
        <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />

        {/* HR routes */}
        <Route path="/hr" element={<ProtectedRoute roles={['hr', 'admin']}><HRDashboard /></ProtectedRoute>} />
        <Route path="/hr/analytics" element={<ProtectedRoute roles={['hr', 'admin']}><HRAnalytics /></ProtectedRoute>} />
        <Route path="/hr/comparison/:sessionId" element={<ProtectedRoute roles={['hr', 'admin']}><CandidateComparison /></ProtectedRoute>} />
        <Route path="/hr/create-session" element={<ProtectedRoute roles={['hr', 'admin']}><CreateSession /></ProtectedRoute>} />
        <Route path="/hr/session/:sessionId" element={<ProtectedRoute roles={['hr', 'admin']}><SessionDetail /></ProtectedRoute>} />
        <Route path="/hr/live/:sessionId" element={<ProtectedRoute roles={['hr', 'admin']}><LiveInterview /></ProtectedRoute>} />
        <Route path="/hr/livekit-monitor/:sessionId" element={<ProtectedRoute roles={['hr', 'admin']}><LiveKitMonitorDashboard /></ProtectedRoute>} />

        {/* Candidate interview join (public via token) */}
        <Route path="/interview/:token" element={<CandidateJoin />} />
      </Routes>
      <Toaster position="top-right" />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
