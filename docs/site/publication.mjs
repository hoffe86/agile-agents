// Exact repository-relative paths: adding a file here is a publication decision.
export const documents = [
  'docs/introduction/index.md',
  'docs/introduction/concepts.md',
  'docs/introduction/capabilities.md',
  'docs/codebase/ARCHITECTURE.md',
  'docs/codebase/STRUCTURE.md',
  'docs/codebase/STACK.md',
  'docs/codebase/CONVENTIONS.md',
  'docs/codebase/INTEGRATIONS.md',
  'docs/codebase/TESTING.md',
  'docs/codebase/CONCERNS.md',
  'docs/getting-started/index.md',
  'docs/getting-started/installation.md',
  'docs/getting-started/bootstrap.md',
  'docs/getting-started/first-requirement.md',
  'docs/flow/index.md',
  'docs/flow/research.md',
  'docs/flow/plan.md',
  'docs/flow/implement.md',
  'docs/flow/review.md',
  'docs/flow/handoffs.md',
  'docs/flow/budget.md',
  'docs/README.md',
  'docs/customization-ownership.md',
  'docs/AGENTS-MD-MAPPING.md',
  'docs/adr/0001-code-localisation-backend-default.md',
  'docs/adr/0002-self-benchmarking-harness-composition.md',
  'docs/adr/0003-test-bar-gate-placement.md',
  'docs/adr/0004-cost-envelope-thresholds-and-stop-on-breach.md',
  'docs/adr/0005-agents-md-generation-strategy.md',
  'docs/adr/0006-run-event-log-schema.md',
  'docs/adr/0007-model-tier-convention.md',
  'docs/adr/0008-layered-evaluation-strategy.md',
  'docs/adr/0009-merge-coding-and-testing-agents.md',
  'docs/adr/0010-split-general-review-lens-from-orchestrator.md',
  'docs/adr/0011-reviewer-agent-naming.md',
  'docs/adr/0012-data-scientist-agent.md',
  'docs/adr/0013-senior-agent-judgement.md',
  'docs/adr/0014-skill-evaluation-with-waza.md',
  'docs/adr/0015-deepeval-for-pipeline-evaluation.md',
  'docs/adr/0016-t-shaped-research-and-plan.md',
  'eval/README.md',
  'eval/skills/README.md',
  'eval/pipeline/trajectory/README.md',
  'eval/pipeline/custom-eval/README.md',
  'eval/deepeval/README.md',
  'eval/pipeline/scoring-rubric.md',
];

export const assets = [
  'docs/assets/rpi-pipeline.png',
  'docs/assets/delivery-handovers.png',
  'docs/assets/budget-checkpoint.png',
  'docs/assets/delivery-sequence.png',
  'docs/assets/technical-test-gate.png',
];
export const repositoryUrl = 'https://github.com/hoffe86/agile-agents';
export const sourceBranch = 'main';

export function editUrl({ docPath }) {
  return `${repositoryUrl}/edit/${sourceBranch}/${docPath.split('/').map(encodeURIComponent).join('/')}`;
}
