// Map of LaTeX command names (without backslash) to Unicode characters
const LATEX_TO_UNICODE: Record<string, string> = {
  // Arrows
  rightarrow: '→',
  longrightarrow: '→',
  to: '→',
  leftarrow: '←',
  longleftarrow: '←',
  gets: '←',
  leftrightarrow: '↔',
  longleftrightarrow: '↔',
  Rightarrow: '⇒',
  Longrightarrow: '⇒',
  Leftarrow: '⇐',
  Longleftarrow: '⇐',
  Leftrightarrow: '⇔',
  Longleftrightarrow: '⇔',
  uparrow: '↑',
  downarrow: '↓',
  updownarrow: '↕',
  mapsto: '↦',
  longmapsto: '↦',

  // Comparisons & Relations
  leq: '≤',
  le: '≤',
  geq: '≥',
  ge: '≥',
  neq: '≠',
  ne: '≠',
  approx: '≈',
  equiv: '≡',
  sim: '∼',
  simeq: '≃',
  ll: '≪',
  gg: '≫',

  // Arithmetic & Operations
  pm: '±',
  mp: '∓',
  times: '×',
  div: '÷',
  cdot: '·',
  bullet: '•',
  dots: '…',
  ldots: '…',
  cdots: '…',
  circ: '∘',
  ast: '∗',
  star: '★',

  // Set theory & logic
  in: '∈',
  notin: '∉',
  subset: '⊂',
  subseteq: '⊆',
  supset: '⊃',
  supseteq: '⊇',
  cap: '∩',
  cup: '∪',
  forall: '∀',
  exists: '∃',
  neg: '¬',
  land: '∧',
  lor: '∨',
  infty: '∞',
  partial: '∂',
  nabla: '∇',

  // Greek letters
  alpha: 'α',
  beta: 'β',
  gamma: 'γ',
  Gamma: 'Γ',
  delta: 'δ',
  Delta: 'Δ',
  epsilon: 'ε',
  theta: 'θ',
  lambda: 'λ',
  Lambda: 'Λ',
  mu: 'μ',
  pi: 'π',
  sigma: 'σ',
  Sigma: 'Σ',
  tau: 'τ',
  phi: 'φ',
  Phi: 'Φ',
  omega: 'ω',
  Omega: 'Ω',

  // Scientific & Calculus notation
  sqrt: '√',
  cbrt: '∛',
  deg: '°',
  degree: '°',
  sum: '∑',
  prod: '∏',
  int: '∫',
  hbar: 'ℏ',
};

const MATH_OPERATOR_REGEX = /[→←↔⇒⇐⇔↑↓↕↦=<>≤≥≠≈≡∼≃≪≫±∓×÷·•…∘∈∉⊂⊆∩∪∀∃¬∧∨∞∂\+\-\*\/\^α-ωΑ-Ω√²³°]/;

/**
 * Normalizes LaTeX math symbols, arrows, and expressions into clean Unicode for UI display.
 * Protects currency amounts ($100, $50M, $12.50) from being stripped.
 */
export function humanizeSymbols(text: string): string {
  if (!text) return '';

  let result = text;

  // 1. Unwrap \text{...}, \mathrm{...}, \mathbf{...}, \mathit{...}
  result = result.replace(/\\(?:text|mathrm|mathbf|mathit)\{([^}]+)\}/g, '$1');

  // 2. Replace known LaTeX commands with Unicode symbols
  result = result.replace(
    /\\([a-zA-Z]+)/g,
    (match: string, cmd: string): string => {
      return LATEX_TO_UNICODE[cmd] ?? match;
    }
  );

  // 3. Remove enclosing dollar math delimiters ($expr$), strictly protecting currency amounts
  result = result.replace(
    /\$([^$\n]+?)\$/g,
    (match: string, inner: string): string => {
      if (MATH_OPERATOR_REGEX.test(inner) || /^\s*[a-zA-Z]\s*$/.test(inner)) {
        return inner;
      }
      return match;
    }
  );

  // 4. Strip any dangling/unclosed dollar signs adjacent to a math or arrow symbol
  result = result.replace(
    /\$\s*([→←↔⇒⇐⇔↑↓↕↦≤≥≠≈≡∼≃≪≫±∓×÷·•…∘∈∉⊂⊆∩∪∀∃¬∧∨∞∂α-ωΑ-Ω])/g,
    '$1'
  );
  result = result.replace(
    /([→←↔⇒⇐⇔↑↓↕↦≤≥≠≈≡∼≃≪≫±∓×÷·•…∘∈∉⊂⊆∩∪∀∃¬∧∨∞∂α-ωΑ-Ω])\s*\$/g,
    '$1'
  );

  return result;
}
