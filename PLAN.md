# Signal Loop product and development plan

## Product direction

Signal Loop will give product and engineering teams a durable view of customer evidence. The product should help teams recover what customers said, understand the context, find related evidence, and eventually use qualitative and product-usage data to inform priorities.

The initial example dataset will contain mock support conversations about a fictional chat product. The platform and its data model must remain generic.

## Roadmap

### Milestone 1: Ingest and ask

A user can ingest customer conversations, search their contents, and hold a conversation whose answers cite the original evidence.

### Milestone 2: Living problem board

The platform groups related evidence into customer problems, preserves deferred problems, and resurfaces them when new evidence arrives.

### Milestone 3: Product-usage analytics

Teams can understand feature adoption and product behaviour alongside qualitative customer feedback.

### Milestone 4: Prioritisation and outcomes

Teams can compare opportunities using customer evidence, product usage, strategy, and engineering constraints, then assess whether shipped changes improved customer outcomes.

Milestones after the first are provisional and will be challenged and refined before implementation.

## Milestone 1 development sprints

The developer has 8–10 hours per week. Sprints are ordered work packages; their duration will be estimated as each sprint is refined.

### Sprint 1: Server and file CRUD

Set up Django, PostgreSQL, and Docker. Design the initial user and file models, then implement APIs to upload, list, inspect, update metadata for, and delete files.

Completion criteria:

- The Django server and PostgreSQL start locally through documented commands.
- Database migrations run successfully.
- File records and uploaded content persist correctly.
- The API validates requests and returns useful error responses.
- File content is immutable after upload; replacing content means deleting and uploading again.

The user model is designed now so ownership can be added cleanly, but authentication, multiple users, and shared workspaces are deferred during the local prototype.

### Sprint 2: Conversation ingestion

Define a generic JSON contract for conversations, create the mock chat-product dataset, model imported conversations and messages, and parse accepted uploads into those records.

Completion criteria:

- A valid upload produces conversations and messages that can be inspected through the API.
- Invalid input returns actionable validation errors.
- Deleting an upload removes all records derived from it.
- Source-specific fields can be retained without making the core schema source-specific.

### Sprint 3: Retrieval

Study and compare keyword, semantic, and hybrid retrieval. Choose an approach only after understanding the tradeoffs, then implement search APIs and a small retrieval evaluation set.

Completion criteria:

- Prepared questions retrieve their expected source messages with enough surrounding context.
- Exact identifiers and semantically similar descriptions are covered by the evaluation set.
- Search results identify the source upload, conversation, and messages needed for later citations.

The retrieval technology and detailed indexing design are intentionally deferred until this sprint is discussed.

### Sprint 4: Conversational answers

Integrate the OpenAI API, persist AI chat sessions, support follow-up questions, retrieve fresh evidence for each question, and return citations to source messages.

Completion criteria:

- Follow-up questions can refer to earlier topics in the same AI chat session.
- Every factual answer is supported by imported customer evidence.
- Citations resolve to the original messages and their conversation context.
- Ambiguous follow-ups trigger clarification, and unsupported questions receive an explicit insufficient-evidence response.
- Previous AI answers help interpret follow-ups but are never treated as customer evidence.

### Sprint 5: End-to-end reliability

Exercise the complete API workflow, improve failure handling, and document local operation.

Completion criteria:

- The ingest, inspect, search, ask, cite, and delete journey is reproducible through API requests.
- Ingestion and OpenAI API failures produce recoverable states.
- Deletion removes source data and its derived search data.
- Retrieval and conversational evaluation cases pass at an agreed quality threshold.
- Latency and OpenAI token usage are recorded so later decisions have a baseline.

## Current technical decisions

- Use Django for the backend API and PostgreSQL as the sole database.
- Use PostgreSQL text fields for unrestricted conversation content and JSONB where flexible source metadata is needed.
- Keep imported customer conversations separate from conversations users have with the AI.
- Own the retrieval and citation pipeline rather than delegating file search to a hosted system.
- Use OpenAI APIs for answer generation while storing application state in Django.
- Run the first version locally with one implicit workspace and mock data.
- Defer React, sign-in, workspace isolation, external integrations, and deployment.

Meaningful product and technology choices will be discussed before they are locked. In particular, retrieval architecture, OpenAI model selection, detailed database schemas, and later milestone designs remain open.
