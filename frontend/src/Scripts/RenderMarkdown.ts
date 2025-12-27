import DOMPurify from "dompurify";
import Hljs from "highlight.js/lib/core";
import Bash from "highlight.js/lib/languages/bash";
import Csharp from "highlight.js/lib/languages/csharp";
import Css from "highlight.js/lib/languages/css";
import Javascript from "highlight.js/lib/languages/javascript";
import Json from "highlight.js/lib/languages/json";
import Python from "highlight.js/lib/languages/python";
import Scss from "highlight.js/lib/languages/scss";
import Sql from "highlight.js/lib/languages/sql";
import Typescript from "highlight.js/lib/languages/typescript";
import Xml from "highlight.js/lib/languages/xml";
import { marked } from "marked";

import("highlight.js/styles/github.css");

/* eslint-disable @typescript-eslint/naming-convention */

// Register languages for syntax highlighting
Hljs.registerLanguage("bash", Bash);
Hljs.registerLanguage("sh", Bash);
Hljs.registerLanguage("shell", Bash);
Hljs.registerLanguage("csharp", Csharp);
Hljs.registerLanguage("cs", Csharp);
Hljs.registerLanguage("c#", Csharp);
Hljs.registerLanguage("css", Css);
Hljs.registerLanguage("javascript", Javascript);
Hljs.registerLanguage("js", Javascript);
Hljs.registerLanguage("jsx", Javascript);
Hljs.registerLanguage("json", Json);
Hljs.registerLanguage("python", Python);
Hljs.registerLanguage("py", Python);
Hljs.registerLanguage("scss", Scss);
Hljs.registerLanguage("sass", Scss);
Hljs.registerLanguage("sql", Sql);
Hljs.registerLanguage("typescript", Typescript);
Hljs.registerLanguage("ts", Typescript);
Hljs.registerLanguage("tsx", Typescript);
Hljs.registerLanguage("xml", Xml);
Hljs.registerLanguage("html", Xml);

/**
 * Configures marked options for GFM (GitHub Flavored Markdown) support
 */
marked.setOptions({
	gfm: true, // Enable GitHub Flavored Markdown
	breaks: true, // Convert \n to <br>
});

/**
 * Applies syntax highlighting to code blocks in HTML
 * @param htmlString - HTML string containing code blocks
 * @returns HTML string with highlighted code blocks
 */
function highlightCodeBlocks(htmlString: string): string {
	// Replace code blocks with highlighted versions
	return htmlString.replace(
		/<pre><code(?:\s+class="language-(\w+)")?>([\s\S]*?)<\/code><\/pre>/g,
		(match, language, code) => {
			// Decode HTML entities in code
			const decodedCode = code
				.replace(/&lt;/g, "<")
				.replace(/&gt;/g, ">")
				.replace(/&amp;/g, "&")
				.replace(/&quot;/g, '"')
				.replace(/&#39;/g, "'");

			try {
				// Try to highlight with specified language or auto-detect
				const result = language
					? Hljs.highlight(decodedCode, { language })
					: Hljs.highlightAuto(decodedCode);

				// Return highlighted code with language class
				const langClass = language || result.language || "";
				return `<pre><code class="hljs${langClass ? ` language-${langClass}` : ""}">${result.value}</code></pre>`;
			} catch (error) {
				// If highlighting fails, return original code block
				console.warn("Failed to highlight code block:", error);
				return match;
			}
		},
	);
}

/**
 * Safely renders markdown to HTML with sanitization
 * @param markdown - The markdown string to render
 * @returns Sanitized HTML string
 */
export function RenderMarkdown(markdown: string): string {
	if (!markdown || typeof markdown !== "string") {
		return "";
	}

	try {
		// Convert markdown to HTML
		const rawHtml = marked.parse(markdown, { async: false }) as string;

		// Apply syntax highlighting to code blocks
		const highlightedHtml = highlightCodeBlocks(rawHtml);

		// Sanitize HTML to prevent XSS attacks
		const cleanHtml = DOMPurify.sanitize(highlightedHtml, {
			ALLOWED_TAGS: [
				"h1",
				"h2",
				"h3",
				"h4",
				"h5",
				"h6",
				"p",
				"br",
				"strong",
				"em",
				"u",
				"s",
				"del",
				"code",
				"pre",
				"blockquote",
				"ul",
				"ol",
				"li",
				"a",
				"img",
				"table",
				"thead",
				"tbody",
				"tr",
				"th",
				"td",
				"hr",
				"input",
				"span",
			],
			ALLOWED_ATTR: [
				"href",
				"src",
				"alt",
				"title",
				"class",
				"type",
				"checked",
				"disabled",
				"target",
				"rel",
			],
			ALLOW_DATA_ATTR: false,
			// Add noopener and noreferrer to external links for security
			ADD_ATTR: ["target", "rel"],
			RETURN_DOM: false,
			RETURN_DOM_FRAGMENT: false,
		});

		// Add rel="noopener noreferrer" to external links
		return cleanHtml.replace(
			/<a\s+href="(https?:\/\/[^"]+)"/gi,
			'<a href="$1" target="_blank" rel="noopener noreferrer">',
		);
	} catch (error) {
		console.error("Error rendering markdown:", error);
		// Fallback: return escaped plain text
		return DOMPurify.sanitize(markdown, { ALLOWED_TAGS: [] });
	}
}
