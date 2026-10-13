import { DEEP_AGENTS_COMPARISON_THREAD_STORAGE_KEY } from "@langchain/playground-preview-protocol";

import { SubagentCardsChat } from "../deep-agent-subagent-cards/SubagentCardsChat";

// Docs interactive example only — not a UI pattern demo.
// Reuses the subagent-cards chat UI and deep_agent_subagent_cards agent to
// illustrate comparing DeepAgents, LangChain, and LangGraph in the docs.
const PRESETS = ["Compare DeepAgents, LangChain, and LangGraph for building an agent"];

export default function DeepAgentsComparisonPreview() {
  return (
    <SubagentCardsChat
      presets={PRESETS}
      threadStorageKey={DEEP_AGENTS_COMPARISON_THREAD_STORAGE_KEY}
    />
  );
}
