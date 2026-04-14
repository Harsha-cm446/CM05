"""
Reinforcement Learning Adaptation Engine
─────────────────────────────────────────
Component 4: Adaptive interview using RL (PPO)

Architecture:
  ┌─────────────────────────────────────────────┐
  │           Interview Environment              │
  │                                               │
  │  State Space:                                 │
  │    • confidence_level (0-1)                   │
  │    • performance_score (0-1)                  │
  │    • stress_level (0-1)                       │
  │    • question_number (normalized)             │
  │    • current_difficulty (0=easy,1=med,2=hard) │
  │    • time_remaining (0-1)                     │
  │    • topic_coverage (0-1)                     │
  │    • streak_correct (normalized)              │
  │                                               │
  │  Action Space:                                │
  │    0: Ask easier question                     │
  │    1: Ask same difficulty                     │
  │    2: Ask harder question                     │
  │    3: Switch topic (same difficulty)           │
  │    4: Ask follow-up (probe deeper)            │
  │    5: Ask supportive/clarification question   │
  │                                               │
  │  Reward Function (multi-objective):           │
  │    R = w1*coverage + w2*engagement             │
  │      + w3*discrimination - w4*frustration      │
  │      + w5*fairness_penalty                     │
  └─────────────────────────────────────────────┘

PPO Training Pipeline:
  1. Simulate interviews with synthetic candidates
  2. Train PPO agent on cumulative reward
  3. Deploy agent for real-time difficulty adaptation
"""

import math
import random
from typing import Dict, Any, List, Optional, Tuple
from collections import deque

import numpy as np


# ── Custom Interview Environment (OpenAI Gym-compatible) ──

class InterviewEnvironment:
    """
    Custom RL environment for adaptive interview difficulty control.

    Follows the OpenAI Gym interface pattern:
      env.reset() → state
      env.step(action) → state, reward, done, info
    """

    # State space dimensions
    STATE_DIM = 8
    # Action space size
    ACTION_DIM = 6

    # Action definitions
    ACTIONS = {
        0: "easier_question",
        1: "same_difficulty",
        2: "harder_question",
        3: "switch_topic",
        4: "follow_up_deep",
        5: "supportive_question",
    }

    def __init__(self, max_questions: int = 15, target_score: float = 0.65):
        self.max_questions = max_questions
        self.target_score = target_score

        # State variables
        self.confidence = 0.5
        self.performance = 0.5
        self.stress = 0.3
        self.question_number = 0
        self.current_difficulty = 1  # 0=easy, 1=medium, 2=hard
        self.time_remaining = 1.0
        self.topic_coverage = 0.0
        self.streak_correct = 0

        # History
        self.scores_history: List[float] = []
        self.difficulty_history: List[int] = []
        self.action_history: List[int] = []
        self.topics_covered: set = set()
        self.total_topics = 8  # Estimated number of topics

        # Done flag
        self.done = False

    def reset(self) -> np.ndarray:
        """Reset environment for a new interview."""
        self.confidence = 0.5
        self.performance = 0.5
        self.stress = 0.3
        self.question_number = 0
        self.current_difficulty = 1
        self.time_remaining = 1.0
        self.topic_coverage = 0.0
        self.streak_correct = 0
        self.scores_history = []
        self.difficulty_history = []
        self.action_history = []
        self.topics_covered = set()
        self.done = False
        return self._get_state()

    def _get_state(self) -> np.ndarray:
        """Get current state as a numpy array."""
        return np.array([
            self.confidence,
            self.performance,
            self.stress,
            self.question_number / max(self.max_questions, 1),
            self.current_difficulty / 2.0,
            self.time_remaining,
            self.topic_coverage,
            min(self.streak_correct / 5.0, 1.0),
        ], dtype=np.float32)

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """Execute an action and return (next_state, reward, done, info)."""
        if self.done:
            return self._get_state(), 0.0, True, {"message": "Interview already ended"}

        # Record action
        self.action_history.append(action)

        # Apply action to modify difficulty
        if action == 0:  # easier
            self.current_difficulty = max(0, self.current_difficulty - 1)
        elif action == 2:  # harder
            self.current_difficulty = min(2, self.current_difficulty + 1)
        elif action == 3:  # switch topic
            new_topic = random.randint(0, self.total_topics - 1)
            self.topics_covered.add(new_topic)
        elif action == 4:  # follow-up (same topic, deeper)
            pass  # Keep same difficulty and topic
        elif action == 5:  # supportive
            self.current_difficulty = max(0, self.current_difficulty - 1)

        self.difficulty_history.append(self.current_difficulty)

        # Simulate candidate response
        score = self._simulate_response(action)
        self.scores_history.append(score)

        # Update state
        self._update_state(score, action)

        # Check if done
        self.question_number += 1
        self.time_remaining = max(0, 1.0 - self.question_number / self.max_questions)

        if self.question_number >= self.max_questions or self.time_remaining <= 0:
            self.done = True

        # Compute reward
        reward = self._compute_reward(score, action)

        info = {
            "score": score,
            "difficulty": self.current_difficulty,
            "action_name": self.ACTIONS.get(action, "unknown"),
            "question_number": self.question_number,
        }

        return self._get_state(), reward, self.done, info

    def _simulate_response(self, action: int) -> float:
        """Simulate a candidate's response score based on difficulty and state."""
        # Base probability of correct answer depends on difficulty vs ability
        ability = self.performance * 0.7 + self.confidence * 0.3
        difficulty_factor = (self.current_difficulty + 1) / 3.0

        # IRT-inspired probability: P(correct) = sigmoid(ability - difficulty)
        logit = (ability - difficulty_factor) * 3
        p_correct = 1 / (1 + math.exp(-logit))

        # Add noise
        noise = random.gauss(0, 0.1)
        score = max(0, min(1, p_correct + noise))

        return score

    def _update_state(self, score: float, action: int):
        """Update internal state after receiving a response."""
        # Performance: exponential moving average
        alpha = 0.3
        self.performance = alpha * score + (1 - alpha) * self.performance

        # Confidence: increases with correct answers, decreases with wrong
        if score >= 0.6:
            self.confidence = min(1.0, self.confidence + 0.05)
            self.streak_correct += 1
        else:
            self.confidence = max(0.0, self.confidence - 0.08)
            self.streak_correct = 0

        # Stress: increases with hard questions, decreases with easier ones
        difficulty_stress = (self.current_difficulty - 1) * 0.05
        score_stress = -0.03 if score >= 0.5 else 0.05
        self.stress = max(0, min(1, self.stress + difficulty_stress + score_stress))

        # Topic coverage
        self.topic_coverage = len(self.topics_covered) / max(self.total_topics, 1)

    def _compute_reward(self, score: float, action: int) -> float:
        """
        Multi-objective reward function.

        Components:
          1. Coverage reward: Encourage topic diversity
          2. Engagement reward: Keep candidate in optimal challenge zone
          3. Discrimination reward: Questions that differentiate ability levels
          4. Frustration penalty: Penalize excessive difficulty for struggling candidates
          5. Fairness penalty: Penalize extreme difficulty oscillation
        """
        # Weight configuration
        w_coverage = 0.20
        w_engagement = 0.30
        w_discrimination = 0.25
        w_frustration = 0.15
        w_fairness = 0.10

        # 1. Coverage reward
        coverage_reward = self.topic_coverage

        # 2. Engagement reward (optimal challenge zone: score 0.4-0.8)
        if 0.4 <= score <= 0.8:
            engagement_reward = 1.0
        elif 0.2 <= score <= 0.9:
            engagement_reward = 0.5
        else:
            engagement_reward = 0.0

        # 3. Discrimination reward (questions that aren't too easy or too hard)
        if 0.3 <= score <= 0.7:
            discrimination_reward = 1.0  # Good discriminating question
        else:
            discrimination_reward = 0.3

        # 4. Frustration penalty
        frustration_penalty = 0.0
        if self.stress > 0.7 and self.current_difficulty == 2:
            frustration_penalty = 0.5  # High stress + hard question
        if score < 0.3 and self.current_difficulty == 2:
            frustration_penalty += 0.3  # Failed hard question

        # 5. Fairness penalty (difficulty oscillation)
        fairness_penalty = 0.0
        if len(self.difficulty_history) >= 3:
            recent = self.difficulty_history[-3:]
            oscillation = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent)))
            if oscillation > 2:
                fairness_penalty = 0.3

        reward = (
            w_coverage * coverage_reward +
            w_engagement * engagement_reward +
            w_discrimination * discrimination_reward -
            w_frustration * frustration_penalty -
            w_fairness * fairness_penalty
        )

        return reward


# ── PPO Agent ─────────────────────────────────────────

class PPOAgent:
    """
    Proximal Policy Optimization agent for interview adaptation.

    Uses a simple neural network policy (numpy-based for portability).
    For production, use stable-baselines3 PPO with PyTorch.
    """

    def __init__(
        self,
        state_dim: int = InterviewEnvironment.STATE_DIM,
        action_dim: int = InterviewEnvironment.ACTION_DIM,
        learning_rate: float = 3e-4,
        gamma: float = 0.99,
        epsilon: float = 0.2,
        epochs: int = 4,
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.lr = learning_rate
        self.gamma = gamma
        self.epsilon = epsilon
        self.epochs = epochs

        # Simple linear policy (for demonstration)
        # Production: use PyTorch nn.Module
        self.policy_weights = np.random.randn(state_dim, action_dim) * 0.1
        self.policy_bias = np.zeros(action_dim)
        self.value_weights = np.random.randn(state_dim, 1) * 0.1
        self.value_bias = np.zeros(1)

        # Experience buffer
        self.states: List[np.ndarray] = []
        self.actions: List[int] = []
        self.rewards: List[float] = []
        self.log_probs: List[float] = []
        self.values: List[float] = []
        self.dones: List[bool] = []

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        e = np.exp(x - np.max(x))
        return e / e.sum()

    def get_action(self, state: np.ndarray) -> Tuple[int, float]:
        """Select action using current policy."""
        logits = state @ self.policy_weights + self.policy_bias
        probs = self._softmax(logits)
        action = np.random.choice(self.action_dim, p=probs)
        log_prob = np.log(probs[action] + 1e-8)
        return int(action), float(log_prob)

    def get_value(self, state: np.ndarray) -> float:
        """Estimate state value."""
        value = state @ self.value_weights + self.value_bias
        return float(np.asarray(value).reshape(-1)[0])

    def store_transition(
        self, state: np.ndarray, action: int, reward: float,
        log_prob: float, value: float, done: bool,
    ):
        """Store a transition in the experience buffer."""
        self.states.append(state)
        self.actions.append(action)
        self.rewards.append(reward)
        self.log_probs.append(log_prob)
        self.values.append(value)
        self.dones.append(done)

    def compute_returns(self) -> np.ndarray:
        """Compute discounted returns with GAE."""
        returns = np.zeros(len(self.rewards))
        running_return = 0
        for t in reversed(range(len(self.rewards))):
            if self.dones[t]:
                running_return = 0
            running_return = self.rewards[t] + self.gamma * running_return
            returns[t] = running_return
        return returns

    def update(self):
        """Update policy using PPO objective."""
        if len(self.states) == 0:
            return

        states = np.array(self.states)
        actions = np.array(self.actions, dtype=int).reshape(-1)
        old_log_probs = np.array(self.log_probs, dtype=float).reshape(-1)
        returns = self.compute_returns().reshape(-1)
        values = np.array(self.values, dtype=float).reshape(-1)
        advantages = returns - values

        # Normalize advantages
        if len(advantages) > 1:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        for _ in range(self.epochs):
            for i in range(len(states)):
                state = states[i]
                action = int(actions[i])

                # Forward pass
                logits = state @ self.policy_weights + self.policy_bias
                probs = self._softmax(logits)
                new_log_prob = np.log(probs[action] + 1e-8)

                # PPO ratio
                ratio = np.exp(new_log_prob - float(old_log_probs[i]))
                clipped_ratio = np.clip(ratio, 1 - self.epsilon, 1 + self.epsilon)
                adv_i = float(advantages[i])
                policy_loss = -min(ratio * adv_i, clipped_ratio * adv_i)

                # Value loss
                new_value_arr = state @ self.value_weights + self.value_bias
                new_value = float(np.asarray(new_value_arr).reshape(-1)[0])
                ret_i = float(returns[i])
                value_loss = (new_value - ret_i) ** 2

                # Gradient update (simplified)
                # Policy gradient
                grad = np.zeros(self.action_dim)
                grad[action] = adv_i
                policy_grad = np.outer(state, grad)
                self.policy_weights -= self.lr * policy_grad * 0.01

                # Value gradient
                value_grad = 2 * (new_value - ret_i) * state
                self.value_weights -= self.lr * value_grad.reshape(-1, 1) * 0.01

        # Clear buffer
        self.states.clear()
        self.actions.clear()
        self.rewards.clear()
        self.log_probs.clear()
        self.values.clear()
        self.dones.clear()

    def train(self, env: InterviewEnvironment, episodes: int = 1000) -> Dict[str, List[float]]:
        """Train the PPO agent on the interview environment."""
        episode_rewards = []
        episode_lengths = []

        for ep in range(episodes):
            state = env.reset()
            total_reward = 0
            steps = 0

            while not env.done:
                action, log_prob = self.get_action(state)
                value = self.get_value(state)

                next_state, reward, done, info = env.step(action)

                self.store_transition(state, action, reward, log_prob, value, done)

                state = next_state
                total_reward += reward
                steps += 1

            # Update policy after each episode
            self.update()

            episode_rewards.append(total_reward)
            episode_lengths.append(steps)

            if (ep + 1) % 100 == 0:
                avg_reward = np.mean(episode_rewards[-100:])
                print(f"  Episode {ep + 1}/{episodes} | Avg Reward: {avg_reward:.3f}")

        return {
            "rewards": episode_rewards,
            "lengths": episode_lengths,
        }


# ── RL Adaptation Service ─────────────────────────────

class RLAdaptationService:
    """High-level service for RL-based interview adaptation."""

    def __init__(self):
        self.agent = PPOAgent()
        self.env = InterviewEnvironment()
        self._is_trained = False
        self._session_envs: Dict[str, InterviewEnvironment] = {}
        # Per-session guardrail metadata for safe adaptation behavior.
        self._session_adaptation_meta: Dict[str, Dict[str, Any]] = {}

    def train_agent(self, episodes: int = 500) -> Dict[str, Any]:
        """Train the RL agent on simulated interviews."""
        print("🧠 Training RL adaptation agent...")
        results = self.agent.train(self.env, episodes=episodes)
        self._is_trained = True
        print(f"✅ RL agent trained over {episodes} episodes")
        return {
            "episodes": episodes,
            "final_avg_reward": float(np.mean(results["rewards"][-50:])),
            "avg_episode_length": float(np.mean(results["lengths"][-50:])),
        }

    def create_session(self, session_id: str, max_questions: int = 15) -> Dict[str, Any]:
        """Create a new RL-tracked session."""
        env = InterviewEnvironment(max_questions=max_questions)
        env.reset()
        self._session_envs[session_id] = env
        # Prevent unbounded growth — evict oldest if > 500 sessions
        if len(self._session_envs) > 500:
            oldest = next(iter(self._session_envs))
            del self._session_envs[oldest]
        return {"session_id": session_id, "status": "created"}

    def cleanup_session(self, session_id: str):
        """Remove a completed session to free memory."""
        self._session_envs.pop(session_id, None)
        self._session_adaptation_meta.pop(session_id, None)

    def update_topic_coverage(self, session_id: str, topics: List[str]) -> Dict[str, Any]:
        """Inject externally observed topic coverage from real interview context."""
        env = self._session_envs.get(session_id)
        if not env:
            return {"updated": False, "reason": "Session not found"}

        cleaned = [str(t).strip().lower() for t in (topics or []) if str(t).strip()]
        for topic in cleaned:
            env.topics_covered.add(topic)

        # Keep denominator dynamic to avoid punishing narrow role definitions.
        env.total_topics = max(env.total_topics, len(env.topics_covered), 1)
        env.topic_coverage = len(env.topics_covered) / max(env.total_topics, 1)

        return {
            "updated": True,
            "topic_count": len(env.topics_covered),
            "topic_coverage": round(env.topic_coverage, 3),
        }

    def get_next_action(
        self,
        session_id: str,
        confidence: float = 0.5,
        performance: float = 0.5,
        stress: float = 0.3,
    ) -> Dict[str, Any]:
        """Get the next adaptation action for a session."""
        confidence = self._clamp01(confidence)
        performance = self._clamp01(performance)
        stress = self._clamp01(stress)

        env = self._session_envs.get(session_id)
        if not env:
            # No session env — use heuristic with default difficulty index 1 (medium)
            return self._heuristic_action(confidence, performance, stress, current_difficulty_idx=1)

        # Update environment state with Exponential Moving Average for stability
        env.confidence = confidence
        env.performance = performance * 0.3 + env.performance * 0.7  # EMA smoothing
        env.stress = stress

        state = env._get_state()

        if self._is_trained and self._is_signal_reliable(confidence, performance, stress):
            action, _ = self.agent.get_action(state)
        else:
            # Heuristic policy if not trained or signal reliability is low
            action = self._heuristic_policy(confidence, performance, stress)

        action, override_reason = self._apply_safety_guardrails(
            session_id, env, int(action), confidence, performance, stress
        )
        recommended_difficulty = self._action_to_difficulty(action, env.current_difficulty)
        self._update_adaptation_meta(session_id, env.question_number, recommended_difficulty)

        rationale = self._explain_action(action, confidence, performance, stress)
        if override_reason:
            rationale = f"{rationale} Safety override: {override_reason}."

        return {
            "action": int(action),
            "action_name": InterviewEnvironment.ACTIONS.get(action, "unknown"),
            "recommended_difficulty": recommended_difficulty,
            "rationale": rationale,
        }

    def _clamp01(self, value: float, default: float = 0.5) -> float:
        """Clamp potentially noisy signal values into [0, 1]."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        if np.isnan(v):
            return default
        return max(0.0, min(1.0, v))

    def _is_signal_reliable(self, confidence: float, performance: float, stress: float) -> bool:
        """Detect low-confidence/noisy signals and gate RL when needed."""
        if abs(confidence - performance) > 0.55:
            return False
        if stress > 0.9 and performance > 0.85:
            return False
        # Ambiguous center-zone inputs are safer with heuristic policy.
        if 0.45 <= confidence <= 0.55 and 0.45 <= performance <= 0.55 and 0.35 <= stress <= 0.65:
            return False
        return True

    def _apply_safety_guardrails(
        self,
        session_id: str,
        env: InterviewEnvironment,
        action: int,
        confidence: float,
        performance: float,
        stress: float,
    ) -> Tuple[int, str]:
        """Apply production safety overrides for extreme/noisy adaptation outputs."""
        # Extreme stress guardrail: avoid harder jumps when stress is already high.
        if stress >= 0.85 and action == 2:
            return 5, "high stress detected; switched to supportive action"

        # Low-performance guardrail: prevent accidental harder questions.
        if performance <= 0.25 and action == 2:
            return 0, "low performance detected; switched to easier action"

        # Cooldown guardrail: prevent rapid consecutive difficulty jumps.
        current_diff = self._action_to_difficulty(1, env.current_difficulty)
        proposed_diff = self._action_to_difficulty(action, env.current_difficulty)
        meta = self._session_adaptation_meta.setdefault(
            session_id,
            {"last_recommended_difficulty": current_diff, "last_change_question": -999},
        )
        if proposed_diff != current_diff:
            q_num = int(env.question_number)
            if q_num - int(meta.get("last_change_question", -999)) < 2:
                return 1, "difficulty-change cooldown applied"

        return action, ""

    def _update_adaptation_meta(self, session_id: str, question_number: int, recommended_difficulty: str):
        """Track last difficulty change for cooldown control."""
        meta = self._session_adaptation_meta.setdefault(
            session_id,
            {"last_recommended_difficulty": recommended_difficulty, "last_change_question": -999},
        )
        if recommended_difficulty != meta.get("last_recommended_difficulty"):
            meta["last_change_question"] = int(question_number)
        meta["last_recommended_difficulty"] = recommended_difficulty

    def record_response(
        self, session_id: str, score: float
    ) -> Dict[str, Any]:
        """Record a candidate response and get updated state."""
        env = self._session_envs.get(session_id)
        if not env:
            return {"error": "Session not found"}

        # Get action based on current state
        state = env._get_state()
        if self._is_trained:
            action, log_prob = self.agent.get_action(state)
        else:
            action = self._heuristic_policy(env.confidence, env.performance, env.stress)
            log_prob = 0.0

        value = self.agent.get_value(state) if self._is_trained else 0.0

        # Step environment
        next_state, reward, done, info = env.step(action)

        # Store for online learning
        self.agent.store_transition(state, action, reward, log_prob, value, done)

        return {
            "reward": round(reward, 3),
            "done": done,
            "next_difficulty": self._action_to_difficulty(action, env.current_difficulty),
            "action_taken": InterviewEnvironment.ACTIONS.get(action, "unknown"),
            "state_summary": {
                "confidence": round(env.confidence, 2),
                "performance": round(env.performance, 2),
                "stress": round(env.stress, 2),
                "topic_coverage": round(env.topic_coverage, 2),
                "streak": env.streak_correct,
            },
            **info,
        }

    def _heuristic_policy(self, confidence: float, performance: float, stress: float) -> int:
        """Rule-based fallback policy."""
        if stress > 0.7 and performance < 0.4:
            return 5  # Supportive question
        if performance > 0.8 and confidence > 0.7:
            return 2  # Harder question
        if performance < 0.4:
            return 0  # Easier question
        if confidence > 0.6:
            return 4  # Follow-up (probe deeper)
        return 1  # Same difficulty

    def _heuristic_action(
        self,
        confidence: float,
        performance: float,
        stress: float,
        current_difficulty_idx: int = 1,
    ) -> Dict[str, Any]:
        """Heuristic fallback action. Uses current_difficulty_idx to compute
        actual difficulty string instead of hardcoding 'medium'."""
        action = self._heuristic_policy(confidence, performance, stress)
        return {
            "action": action,
            "action_name": InterviewEnvironment.ACTIONS.get(action, "unknown"),
            "recommended_difficulty": self._action_to_difficulty(action, current_difficulty_idx),
            "rationale": self._explain_action(action, confidence, performance, stress),
        }

    def _action_to_difficulty(self, action: int, current: int) -> str:
        difficulties = ["easy", "medium", "hard"]
        if action == 0 or action == 5:
            idx = max(0, current - 1)
        elif action == 2:
            idx = min(2, current + 1)
        else:
            idx = current
        return difficulties[idx]

    def _explain_action(self, action: int, confidence: float, performance: float, stress: float) -> str:
        explanations = {
            0: f"Reducing difficulty — performance ({performance:.0%}) suggests the candidate needs an easier question.",
            1: f"Maintaining difficulty — candidate is performing at an appropriate level ({performance:.0%}).",
            2: f"Increasing difficulty — strong performance ({performance:.0%}) and confidence ({confidence:.0%}) indicate readiness for harder questions.",
            3: f"Switching topic — to ensure comprehensive coverage of required skills.",
            4: f"Asking follow-up — probing deeper based on the candidate's confident response ({confidence:.0%}).",
            5: f"Supportive question — stress level ({stress:.0%}) is high; adjusting to maintain engagement.",
        }
        return explanations.get(action, "Unknown action")


# Singleton
rl_adaptation_service = RLAdaptationService()
