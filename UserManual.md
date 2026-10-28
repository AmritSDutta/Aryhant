# Aryhant User Manual

Welcome to **Aryhant**, your daily AI companion and specialized ICSE Grade 5 teaching assistant!

This guide is written for students, parents, teachers, and Slack workspace members. It explains how to interact with Aryhant, use its educational and study features, request research papers, manage your preferences, and run administrative checks.

---

## 1. Getting Started in Slack

### How to Talk to Aryhant
- **In Public or Private Channels**: Type `@Aryhant` followed by your message or question.
  > *@Aryhant What causes solar eclipses?*
- **In Direct Messages (DMs)**: Simply send your message directly to Aryhant without tagging.
  > *Can you help me practice factors and multiples?*
- **In Message Threads**: When Aryhant replies in a thread, keep the conversation going in that thread to maintain conversation history.
- **Dedicated Slash Commands**:
  - `/research <topic>`: Generates a 2,500-word deep technical whitepaper PDF with verified code.
  - `/deliberate <question>`: Generates a 1,500-word Decision Guide PDF with comparative evaluation matrices.
  - `/preferences`: Opens your personal data and learning habits privacy modal.
  - `/admin` or `/audit`: Runs 15-day retention pruning and generates an operational health audit.

---

## 2. ICSE Grade 5 Study & Learning Companion

Aryhant is customized to support St. Xavier's Grade 5 students under the ICSE syllabus.

### A. Clear, Student-Friendly Explanations
Aryhant provides encouraging, step-by-step explanations without overwhelming technical jargon:
- Plain arithmetic notation (`3/5`, `cm²`, `+`, `-`, `x`, `÷`) rather than complex code snippets.
- Real-life analogies to make abstract concepts intuitive.

### B. Practice Questions & Quizzes
Ask Aryhant for practice questions on any topic:
> *@Aryhant Give me 5 practice questions on equivalent fractions.*

- **Numbered Format**: Questions are clearly numbered (1 to 5 or 10).
- **Hidden Answer Keys**: Answer keys and explanations are grouped at the very end so you can test yourself before checking answers.

### C. Step-by-Step Math Verification
When solving word problems or multi-step arithmetic, Aryhant verifies calculations step-by-step:
> *@Aryhant A rectangular garden is 12 metres long and 8 metres wide. If a path 1 metre wide is built around the outside, what is the area of the path?*

Aryhant breaks down the problem into manageable steps, explaining each calculation clearly.

---

## 3. Universal Study Notes & Infographics

Aryhant can automatically generate high-quality, printable PDF documents directly in your Slack thread.

### A. Handwritten Notebook-Style Study Notes
Want a summary to read before an exam?
> *@Aryhant generate study notes on the Respiratory System*

- **Visual Style**: Clean notebook layout with ruled lines, margin notes, and key takeaways.
- **Delivery**: Compiled in the background and attached as a PDF directly to your Slack thread.

### B. Visual Infographic Posters
Need a visual poster for quick review?
> *@Aryhant create an infographic for the Water Cycle*

- **Visual Style**: Color-coded infographic posters featuring procedural science and geometry diagrams.
- **Delivery**: Uploaded directly to your Slack thread.

---

## 4. Deep Research & Deliberation Guides

For students, parents, researchers, and engineers, Aryhant includes an autonomous, fault-tolerant research pipeline:

### A. Deep Technical Research Whitepapers (`/research`)
> `/research Linux io_uring architecture vs epoll high-throughput networking`
> Or attach a systems architecture diagram:
> `@Aryhant /research Analyze this distributed event-driven pipeline and identify scalability bottlenecks`

- **4-Stream Concurrent Intelligence**: Gathers Google AI Overviews, Tavily Mini-Research deep crawls, Context7 API code implementations, and multi-query search fan-out.
- **Verified Code Execution**: Executes candidate code snippets in isolated microVM sandboxes via Nebius TokenFactory and embeds actual outputs into the whitepaper.
- **Publication PDF**: Delivers a structured ~2,500-word ReportLab PDF whitepaper directly into the Slack conversation thread.

### B. Deliberation & Decision Guides (`/deliberate`)
> `/deliberate Best noise-canceling headphones under $350 for frequent flyers`
> `/deliberate Term life insurance vs whole life for a 32-year-old with young dependents`
> Or attach quotes/spec sheets:
> `@Aryhant /deliberate Compare these two insurance policies on out-of-pocket limits`

- **Decision Synthesis**: Delivers a ~1,500-word Decision Guide PDF with a side-by-side Comparative Evaluation Matrix, contender breakdowns, hidden traps, and step-by-step buying actions.

### C. Key Research Safeguards & Resiliency
1. **Scope Clarification Window**: If your research query is broad or ambiguous (e.g. single generic words), Aryhant posts an informational scope card and gives a **20-second grace period** before automatically proceeding with the inferred scope. Clear technical queries start immediately with 0 delay.
2. **24-Hour Resilient Resume**: If a container restarts or your network drops mid-research, you don't lose progress. Asking again about the topic or continuing in the same thread automatically locates your job from Redis and resumes directly from the last checkpoint, reusing already-fetched intelligence.
3. **Pre-flight Safety Screening**: Dual-layer screening protects against unauthorized access directives, exploits, or malicious code generation. Denials are politely explained and recorded for audit compliance.
4. **Transparent Progress & `[INTERNAL]` Updates**: The research agent updates an interactive Slack TODO board in real time (`⬜` $\to$ `🔄` $\to$ `✅`) and posts intermediate notifications marked `[INTERNAL]` directly into the thread so you always know what phase is executing.

---

## 5. Personalization & Privacy (`/preferences`)

Aryhant remembers your preferred learning habits across conversations (such as wanting step-by-step hints before final answers).

### Managing Your Preferences
Type `/preferences` anywhere in Slack to open your private settings window:
- **Learned Skills**: View topics you have mastered.
- **Active Preferences**: See your recorded habits and learning preferences.
- **Delete Habits**: Click **Delete** next to any item to remove it immediately.
- **Clear All**: Click **Clear All Memories** to exercise your right to be forgotten.

### Data Retention & Privacy
- **Zero PII**: Aryhant only stores pedagogical preferences (e.g. *"prefers visual examples"*), never personal phone numbers, home addresses, or private secrets.
- **15-Day Pruning**: Background operational task logs are automatically pruned after 15 days to keep data footprint minimal.

---

## 6. System Health & Maintenance (`/admin`, `/audit`)

Authorized workspace members and operators can check Aryhant's health and operational status at any time:

- **Slash Commands**: Type `/admin` or `/audit` in any channel.
- **Instant Response**: You will immediately see:
  > *"Running system audit and operational maintenance..."*
- **Audit Report**: Aryhant runs data retention cleanup, computes 7-day task metrics, diagnoses any recent errors, and delivers an operational summary to the channel.

---

## 7. Helpful Tips

1. **Be Specific**: If you need help with a particular chapter or concept, mention the topic name (e.g. *"Grade 5 ICSE Decimals and Percentages"*).
2. **Attach Worksheets**: You can take a photo of your math worksheet or diagram and upload it to Slack; Aryhant will inspect the image and guide you through the problem.
3. **Use Threads**: Keep related questions in the same thread so Aryhant remembers the earlier steps of your discussion.
