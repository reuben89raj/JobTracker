const jobsNode = document.querySelector("#jobs");
const detailPane = document.querySelector("#detail-pane");
const listingTemplate = document.querySelector("#listing-template");
const detailTemplate = document.querySelector("#detail-template");
const summaryNode = document.querySelector("#summary");
const sourceHealthNode = document.querySelector("#source-health");
const resultCount = document.querySelector("#result-count");
const search = document.querySelector("#search");
const company = document.querySelector("#company");
const sourceStatus = document.querySelector("#source-status");
const personalStatus = document.querySelector("#personal-status");

let debounce;
let selectedId = null;

const SECTION_HEADINGS = [
  {
    key: "overview",
    title: "Overview",
    aliases: ["Overview", "Position Summary", "Job Summary", "About the role"],
  },
  {
    key: "responsibilities",
    title: "Responsibilities",
    aliases: [
      "Major Duties/Responsibilities",
      "Major Duties",
      "Duties/Responsibilities",
      "Key Responsibilities",
      "Essential Duties and Responsibilities",
      "Responsibilities",
    ],
  },
  {
    key: "minimum",
    title: "Minimum Qualifications",
    aliases: [
      "Basic Qualifications",
      "Minimum Qualifications",
      "Required Qualifications",
      "Position Requirements",
      "Qualifications",
    ],
  },
  {
    key: "preferred",
    title: "Preferred Qualifications",
    aliases: ["Preferred Qualifications", "Desired Qualifications"],
  },
  {
    key: "special",
    title: "Special Requirements",
    aliases: [
      "Special Requirements",
      "Security, Credentialing, and Eligibility Requirements",
      "Security, Credentialing, and Eligibility",
      "Testing Designated Position",
    ],
  },
];

const SECTION_ORDER = ["overview", "responsibilities", "minimum", "preferred", "special"];
const END_SECTION_ALIASES = [
  "About Us",
  "About ORNL",
  "Benefits",
  "Benefits Summary",
  "Benefits at ORNL",
  "Commitment to Excellence",
  "Drug Free Workplace",
  "Equal Opportunity",
  "Job Application Submission Window",
  "Job Family",
  "Notice to Applicants",
  "Rockstar Rewards",
  "Submission Guidelines",
  "Why Join Us",
];

async function request(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw Error(await response.text());
  }
  return response.json();
}

function cleanDescription(text) {
  return (text || "")
    .replace(/\s+/g, " ")
    .replace(/Careers Home Who We Are Benefits Internship Programs Talent Community/gi, "")
    .replace(/Search by Keyword Show More Options Loading/gi, "")
    .trim();
}

function readableDescription(text) {
  const body = cleanDescription(text);
  if (!body) {
    return "";
  }
  const start = body.search(/Overview:|Overview |Position Summary|Job Summary|About the role/i);
  const sliced = start >= 0 ? body.slice(start).replace(/^Overview:?\s*/i, "") : body;
  const end = sliced.search(
    /Equal Opportunity|Commitment to Excellence|Drug Free Workplace|Rockstar Rewards|Notice to Applicants|E-Verify/i
  );
  return sliced.slice(0, end < 0 ? undefined : end).trim();
}

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function headingLookup() {
  const lookup = new Map();
  SECTION_HEADINGS.forEach((section) => {
    section.aliases.forEach((alias) => lookup.set(alias.toLowerCase(), section.key));
  });
  END_SECTION_ALIASES.forEach((alias) => lookup.set(alias.toLowerCase(), "end"));
  return lookup;
}

function markedDescription(text) {
  const aliases = [
    ...SECTION_HEADINGS.flatMap((section) => section.aliases),
    ...END_SECTION_ALIASES,
  ].sort((a, b) => b.length - a.length);
  const marker = new RegExp(`\\b(${aliases.map(escapeRegex).join("|")})(\\s*:)?`, "g");
  return readableDescription(text).replace(marker, "\n@@$1@@\n");
}

function sentencesFrom(text) {
  return (text.replace(/\s+/g, " ").match(/[^.!?]+[.!?]+(?=\s+[A-Z0-9]|$)|[^.!?]+$/g) || [])
    .map((sentence) => sentence.trim())
    .filter((sentence) => sentence.length > 45 && sentence.length < 360);
}

function bulletItems(text, limit = 8) {
  const normalized = text
    .replace(/\s*[-•]\s+/g, ". ")
    .replace(/\s+(?=(?:US citizenship|Previous experience|Excellent interpersonal|Working knowledge|Solid understanding|Ability to|Experience with|Experience using|An understanding|Familiarity with|Exposure to)\b)/g, ". ")
    .replace(/\s+/g, " ")
    .trim();
  return sentencesFrom(normalized)
    .map((sentence) => sentence.replace(/^[\s:;-]+|[\s:;-]+$/g, ""))
    .filter(Boolean)
    .slice(0, limit);
}

function parseJobSections(text) {
  const lookup = headingLookup();
  const pieces = markedDescription(text).split(/\n@@(.+?)@@\n/g);
  const sections = new Map();
  let currentKey = "overview";

  pieces.forEach((piece, index) => {
    const value = piece.trim();
    if (!value) {
      return;
    }
    if (index % 2 === 1) {
      currentKey = lookup.get(value.toLowerCase()) || currentKey;
      return;
    }
    if (currentKey === "end") {
      return;
    }
    sections.set(currentKey, `${sections.get(currentKey) || ""} ${value}`.trim());
  });

  if (!sections.has("responsibilities")) {
    const fallback = sentencesFrom(readableDescription(text)).slice(0, 4).join(" ");
    if (fallback) {
      sections.set("overview", fallback);
    }
  }
  return sections;
}

function renderSection(container, title, items) {
  if (!items.length) {
    return;
  }
  const section = document.createElement("section");
  section.className = "job-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const list = document.createElement("ul");
  items.forEach((item) => {
    const bullet = document.createElement("li");
    bullet.textContent = item;
    list.appendChild(bullet);
  });
  section.append(heading, list);
  container.appendChild(section);
}

function renderJobSections(container, job) {
  const sections = parseJobSections(job.description);
  container.replaceChildren();
  SECTION_ORDER.forEach((key) => {
    const definition = SECTION_HEADINGS.find((section) => section.key === key);
    renderSection(container, definition.title, bulletItems(sections.get(key) || ""));
  });
  container.hidden = container.children.length === 0;
}

function emptyDetail() {
  return '<div class="empty-detail"><span>&lt;-</span><p>Select a posting to view details.</p></div>';
}

function clearDetail() {
  selectedId = null;
  detailPane.innerHTML = emptyDetail();
  renderSelection();
}

function renderSelection() {
  jobsNode.querySelectorAll(".job-listing").forEach((node) => {
    node.classList.toggle("selected", node.dataset.id === selectedId);
  });
}

function badgeStatus(job) {
  if (job.personal_status && job.personal_status !== "untracked") {
    return {
      label: job.personal_status.replace("_", " "),
      className: job.personal_status,
    };
  }
  return {
    label: job.source_status,
    className: job.source_status,
  };
}

function renderBadge(badge, job) {
  const status = badgeStatus(job);
  badge.textContent = status.label;
  badge.classList.add(status.className);
}

function listing(job) {
  const node = listingTemplate.content.cloneNode(true);
  const button = node.querySelector("button");
  button.dataset.id = job.record_id;
  node.querySelector(".lab").textContent = job.laboratory;
  node.querySelector("h2").textContent = job.title;
  node.querySelector(".meta").textContent = [
    job.location,
    job.posted_date && `Posted ${job.posted_date}`,
  ].filter(Boolean).join(" - ");
  const badge = node.querySelector(".source-badge");
  renderBadge(badge, job);
  button.onclick = () => showDetail(job);
  return node;
}

function showDetail(job) {
  selectedId = job.record_id;
  const node = detailTemplate.content.cloneNode(true);
  node.querySelector(".lab").textContent = job.laboratory;
  node.querySelector("h2").textContent = job.title;
  node.querySelector(".meta").textContent = [
    job.location,
    job.posted_date && `Posted ${job.posted_date}`,
  ].filter(Boolean).join(" - ");
  const badge = node.querySelector(".source-badge");
  renderBadge(badge, job);
  renderJobSections(node.querySelector(".job-sections"), job);
  node.querySelector(".description").textContent = readableDescription(job.description);
  node.querySelector(".evidence").textContent = job.computing_evidence
    ? `Computing fit: ${job.computing_evidence}`
    : "";
  node.querySelector(".apply-link").href = job.url;

  const select = node.querySelector(".personal-select");
  const notes = node.querySelector(".notes");
  select.value = job.personal_status;
  notes.value = job.notes;
  node.querySelector(".save-button").onclick = async () => {
    const updatedJob = await request(`/api/jobs/${job.record_id}`, {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({personal_status: select.value, notes: notes.value}),
    });
    showDetail(updatedJob);
    await load();
  };
  node.querySelector(".close-detail").onclick = clearDetail;
  detailPane.replaceChildren(node);
  renderSelection();
}

function renderSourceHealth(sources, errors) {
  const items = (sources || []).map((source) => {
    const status = source.status === "ok" ? "ok" : "error";
    return `<span class="health-chip ${status}" title="${source.platform}">
      ${source.laboratory}: ${source.kept}/${source.discovered} kept
    </span>`;
  });
  if (errors && errors.length) {
    items.push(`<span class="health-chip error">${errors.length} errors</span>`);
  }
  sourceHealthNode.innerHTML = items.join("");
}

async function summary() {
  const data = await request("/api/summary");
  const okSources = (data.source_health || []).filter((source) => source.status === "ok").length;
  const totalSources = (data.source_health || []).length;
  summaryNode.innerHTML = [
    ["Open", data.source.open || 0],
    ["Labs", data.laboratories.length],
    ["Sources OK", totalSources ? `${okSources}/${totalSources}` : "0"],
    ["Applied", data.personal.applied || 0],
    ["In progress", data.personal.in_progress || 0],
  ].map(([name, count]) => `<div class="metric"><span>${name}</span><strong>${count}</strong></div>`).join("");

  const oldCompany = company.value;
  company.innerHTML = '<option value="all">All companies</option>' +
    data.laboratories.map((lab) => `<option>${lab}</option>`).join("");
  company.value = data.laboratories.includes(oldCompany) ? oldCompany : "all";
  renderSourceHealth(data.source_health, data.errors);
}

async function load() {
  const params = new URLSearchParams({
    q: search.value,
    laboratory: company.value,
    source_status: sourceStatus.value,
    personal_status: personalStatus.value,
  });
  const data = await request(`/api/jobs?${params}`);
  if (!data.jobs.some((job) => job.record_id === selectedId)) {
    clearDetail();
  }
  jobsNode.replaceChildren(...data.jobs.map(listing));
  resultCount.textContent = `${data.count} postings shown`;
  renderSelection();
  summary();
}

[search, company, sourceStatus, personalStatus].forEach((element) => {
  element.oninput = () => {
    clearTimeout(debounce);
    debounce = setTimeout(load, 180);
  };
});

jobsNode.onclick = (event) => {
  if (event.target === jobsNode) {
    clearDetail();
  }
};

document.querySelector("#sync-button").onclick = async () => {
  await request("/api/sync");
  load();
};

load();
