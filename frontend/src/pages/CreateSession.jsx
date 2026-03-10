import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { interviewAPI } from '../services/api';
import toast from 'react-hot-toast';
import { Loader2, Briefcase, ArrowRight, Sliders } from 'lucide-react';

const DEFAULT_WEIGHTS = {
  content: 40,
  keyword: 20,
  depth: 15,
  communication: 15,
  confidence: 10,
};

const WEIGHT_LABELS = {
  content: 'Content Accuracy',
  keyword: 'Keyword Coverage',
  depth: 'Depth of Knowledge',
  communication: 'Communication',
  confidence: 'Confidence',
};

export default function CreateSession() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    job_role: '',
    scheduled_time: '',
    duration_minutes: 30,
    company_name: '',
    description: '',
    job_description: '',
    experience_level: 'mid',
    technical_cutoff: 70,
  });
  const [weights, setWeights] = useState({ ...DEFAULT_WEIGHTS });
  const [showWeights, setShowWeights] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  const handleWeightChange = (key, value) => {
    setWeights((prev) => ({ ...prev, [key]: Math.max(0, Math.min(100, Number(value))) }));
  };

  const totalWeight = Object.values(weights).reduce((s, v) => s + v, 0);

  const resetWeights = () => setWeights({ ...DEFAULT_WEIGHTS });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const total = Object.values(weights).reduce((s, v) => s + v, 0);
      const scoring_weights = total > 0
        ? Object.fromEntries(Object.entries(weights).map(([k, v]) => [k, v / total]))
        : undefined;
      const res = await interviewAPI.createSession({
        ...form,
        duration_minutes: parseInt(form.duration_minutes),
        technical_cutoff: parseFloat(form.technical_cutoff),
        scheduled_time: form.scheduled_time,
        scoring_weights,
      });
      toast.success('Session created!');
      navigate(`/hr/session/${res.data.id}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create session');
    } finally {
      setLoading(false);
    }
  };

  const inputClass = "w-full px-4 py-3 bg-gray-50/80 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-transparent outline-none transition-all";

  return (
    <div className="max-w-2xl mx-auto px-4 py-12">
      <div className="slide-up">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl gradient-bg flex items-center justify-center shadow-sm">
            <Briefcase className="text-white" size={20} />
          </div>
          <h1 className="text-3xl font-bold text-gray-900">Create Interview Session</h1>
        </div>
        <p className="text-gray-500 mb-8 ml-[52px]">Set up a new interview and invite candidates.</p>
      </div>

      <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-sm border border-gray-100 p-8">
        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">Job Role *</label>
            <input
              name="job_role"
              value={form.job_role}
              onChange={handleChange}
              required
              placeholder="e.g. Software Engineer"
              className={inputClass}
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">Company Name</label>
            <input
              name="company_name"
              value={form.company_name}
              onChange={handleChange}
              placeholder="e.g. Acme Corp"
              className={inputClass}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-1.5">Scheduled Date & Time *</label>
              <input
                name="scheduled_time"
                type="datetime-local"
                value={form.scheduled_time}
                onChange={handleChange}
                required
                className={inputClass}
              />
            </div>
            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-1.5">Duration (minutes)</label>
              <select
                name="duration_minutes"
                value={form.duration_minutes}
                onChange={handleChange}
                className={inputClass}
              >
                {[15, 30, 45, 60, 90, 120].map((m) => (
                  <option key={m} value={m}>{m} min</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">Job Description *</label>
            <textarea
              name="job_description"
              value={form.job_description}
              onChange={handleChange}
              required
              rows={5}
              placeholder="Paste the full job description here. Include required skills, responsibilities, qualifications, and tools/technologies..."
              className={inputClass + " resize-none"}
            />
            <p className="mt-1.5 text-xs text-gray-400">AI will generate interview questions based on this JD.</p>
          </div>
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">Experience Level *</label>
            <select
              name="experience_level"
              value={form.experience_level}
              onChange={handleChange}
              required
              className={inputClass}
            >
              <option value="fresher">Fresher (0-1 years)</option>
              <option value="junior">Junior (1-3 years)</option>
              <option value="mid">Mid-Level (3-5 years)</option>
              <option value="senior">Senior (5-8 years)</option>
              <option value="lead">Lead / Staff (8+ years)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">Description</label>
            <textarea
              name="description"
              value={form.description}
              onChange={handleChange}
              rows={3}
              placeholder="Optional session description or instructions for candidates..."
              className={inputClass + " resize-none"}
            />
          </div>

          {/* Technical Cutoff Score */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">Technical Round Cutoff Score (%)</label>
            <div className="flex items-center gap-4">
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={form.technical_cutoff}
                onChange={(e) => setForm({ ...form, technical_cutoff: Number(e.target.value) })}
                className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
              />
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={form.technical_cutoff}
                  onChange={(e) => setForm({ ...form, technical_cutoff: Math.max(0, Math.min(100, Number(e.target.value))) })}
                  className="w-16 px-2 py-1.5 text-center border border-gray-200 rounded-lg text-sm font-mono focus:ring-2 focus:ring-primary-500 outline-none"
                />
                <span className="text-sm text-gray-500">%</span>
              </div>
            </div>
            <p className="mt-1.5 text-xs text-gray-400">Candidates must score at or above this threshold in the Technical round to proceed to the HR round. Default: 70%.</p>
          </div>

          {/* Scoring Weights */}
          <div className="border border-gray-200 rounded-xl overflow-hidden">
            <button
              type="button"
              onClick={() => setShowWeights(!showWeights)}
              className="w-full flex items-center justify-between px-4 py-3 bg-gray-50/80 hover:bg-gray-100 transition-all text-sm font-semibold text-gray-700"
            >
              <span className="flex items-center gap-2">
                <Sliders size={16} className="text-indigo-500" />
                Scoring Weights
              </span>
              <span className="text-xs text-gray-400">{showWeights ? 'Collapse' : 'Customize'}</span>
            </button>
            {showWeights && (
              <div className="p-4 space-y-4">
                <p className="text-xs text-gray-400">
                  Adjust how each dimension contributes to the overall score. Values are normalized automatically.
                </p>
                {Object.entries(WEIGHT_LABELS).map(([key, label]) => (
                  <div key={key}>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-sm text-gray-600">{label}</label>
                      <span className="text-xs font-mono text-gray-400">
                        {totalWeight > 0 ? Math.round((weights[key] / totalWeight) * 100) : 0}%
                      </span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={weights[key]}
                      onChange={(e) => handleWeightChange(key, e.target.value)}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                    />
                  </div>
                ))}
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={resetWeights}
                    className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
                  >
                    Reset to Defaults
                  </button>
                </div>
              </div>
            )}
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full gradient-bg text-white py-3.5 rounded-xl font-semibold flex items-center justify-center gap-2 hover:opacity-90 transition-all disabled:opacity-50 shadow-md hover:shadow-lg"
          >
            {loading ? (
              <span className="inline-block w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <>Create Session <ArrowRight size={18} /></>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
