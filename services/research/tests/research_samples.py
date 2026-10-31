"""Made-up API responses with the same structure as the real ones (checked 2026-10-31).

No real job postings are stored in the repo; these are written for tests.
"""

from typing import Any

GREENHOUSE: dict[str, Any] = {
    "jobs": [
        {
            "id": 101,
            "title": "Senior GenAI Engineer ",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/101",
            "company_name": "Acme AI",
            "location": {"name": "London, UK"},
            "offices": [{"name": "London"}],
            "departments": [{"name": "Applied AI"}],
            "first_published": "2026-10-01T09:00:00-04:00",
            "updated_at": "2026-10-20T09:00:00-04:00",
            "content": "&lt;h2&gt;About the role&lt;/h2&gt;&lt;p&gt;Build RAG features with "
            "Python, design evaluation sets for model output and ship them to customers."
            "&lt;/p&gt;&lt;h2&gt;Benefits&lt;/h2&gt;&lt;ul&gt;&lt;li&gt;Gym&lt;/li&gt;&lt;/ul&gt;",
        },
        {
            "id": 102,
            "title": "Android Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/102",
            "company_name": "Acme AI",
            "location": {"name": "Barcelona"},
            "offices": [],
            "departments": [],
            "first_published": None,
            "updated_at": "2026-10-20T09:00:00-04:00",
            "content": "&lt;p&gt;Kotlin&lt;/p&gt;",
        },
    ],
    "meta": {"total": 2},
}

LEVER: list[dict[str, Any]] = [
    {
        "id": "a1b2",
        "text": "Software Engineer, Machine Learning",
        "hostedUrl": "https://jobs.lever.co/acme/a1b2",
        "categories": {
            "location": "London",
            "allLocations": ["London", "Manchester"],
            "department": "Engineering",
            "team": "ML Platform",
        },
        "country": "GB",
        "workplaceType": "hybrid",
        "createdAt": 1790000000000,
        "descriptionBody": "<div><p>Ship model-backed services.</p></div>",
        "lists": [{"text": "What you'll do", "content": "<li>Build inference APIs</li>"}],
        "additional": "<div>We are an equal opportunity employer.</div>",
    }
]

ASHBY: dict[str, Any] = {
    "apiVersion": "1",
    "jobs": [
        {
            "id": "c3d4",
            "title": "Agentic AI Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/acme/c3d4",
            "department": "Engineering",
            "team": "Agents",
            "location": "London",
            "secondaryLocations": [
                {
                    "location": "Remote (UK)",
                    "address": {"postalAddress": {"addressCountry": "United Kingdom"}},
                }
            ],
            "address": {"postalAddress": {"addressCountry": "United Kingdom"}},
            "workplaceType": "OnSite",
            "isRemote": False,
            "isListed": True,
            "publishedAt": "2026-10-10T12:00:00.000+00:00",
            "descriptionHtml": "<p>Build tool-using agents with LangGraph.</p>",
            "descriptionPlain": "Build tool-using agents with LangGraph.",
            "compensation": {
                "summaryComponents": [
                    {
                        "compensationType": "Salary",
                        "interval": "1 YEAR",
                        "currencyCode": "GBP",
                        "minValue": 90000,
                        "maxValue": 120000,
                    }
                ]
            },
        },
        {"id": "hidden", "title": "Unlisted", "jobUrl": "x", "isListed": False},
    ],
}

ADZUNA_PAGE: dict[str, Any] = {
    "results": [
        {
            "id": "5001",
            "title": "Generative AI Engineer",
            "description": "We are hiring a Generative AI Engineer to build LLM apps with...",
            "redirect_url": "https://www.adzuna.co.uk/jobs/land/ad/5001",
            "created": "2026-10-28T10:00:00Z",
            "company": {"display_name": "Example Bank"},
            "location": {"display_name": "London", "area": ["UK", "London"]},
            "salary_min": 70000,
            "salary_max": 85000,
            "salary_is_predicted": "0",
        },
        {
            "id": "5002",
            "title": "GenAI Engineer",
            "description": "Our client, a fast-growing insurer, needs a GenAI Engineer to build...",
            "redirect_url": "https://www.adzuna.co.uk/jobs/land/ad/5002",
            "created": "2026-10-27T10:00:00Z",
            "company": {"display_name": "Recruit Co"},
            "location": {"display_name": "Leeds", "area": ["UK", "Yorkshire"]},
            "salary_min": 60000,
            "salary_max": 60000,
            "salary_is_predicted": "1",
        },
    ]
}

LONG_MARKDOWN = "Day to day I build evaluation sets for our LLM features. " * 20

FIRECRAWL_SEARCH: dict[str, Any] = {
    "success": True,
    "data": {
        "web": [
            {
                "url": "https://engineering.example.com/our-llm-stack",
                "title": "Our LLM stack",
                "markdown": LONG_MARKDOWN,
            },
            {
                "url": "https://www.reddit.com/r/MachineLearning/comments/abc/genai_engineer_life",
                "title": "What is GenAI engineering really like?",
                "markdown": LONG_MARKDOWN,
            },
            {"url": "https://short.example.com", "title": "Cookie wall", "markdown": "Accept"},
            {"url": "https://uk.linkedin.com/pulse/x", "title": "x", "markdown": LONG_MARKDOWN},
        ]
    },
}
