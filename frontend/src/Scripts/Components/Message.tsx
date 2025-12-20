import { createRef } from "lestin/jsx-runtime";
import {
	IconAiAvatar,
	IconLike,
	IconDislike,
	IconLikeFilled,
	IconDislikeFilled,
	IconClipboard,
	SuggestionIcon,
} from "../Icons.js";
import { baseUrl, ServerEventType } from "../enums.js";
import { i18n } from "../i18n.js";

export function SuggestionListItem(props: {
	text: string;
	onClick: () => void;
}) {
	return (
		<button onClick={props.onClick} class="suggestionItem">
			<SuggestionIcon/>
			<span>{props.text}</span>
		</button>
	);
}

export function AiIsRespondingMessage() {
	return (
		<div class="respondingBox">
			<p>{i18n.respondingMessage}</p>
			<div class="AI-loading">
				<div class="loadingDot">.</div>
				<div class="loadingDot">.</div>
				<div class="loadingDot">.</div>
			</div>
		</div>
	);
}

export function UserMessage(props: { text: string; time: string }) {
	return (
		<div class="messageBox userMessage">
			<div class="messageBody">
				<div class="messageText">{props.text}</div>
			</div>
			<p class="messageTime">{props.time}</p>
		</div>
	);
}

interface AiMessage_Props {
	text: string;
	time: string;
	runId: string;
	isError?: boolean;
	showControls?: boolean;
}

const enum FeedbackType {
	Like,
	Dislike,
}

export function AiMessage(props: AiMessage_Props) {
	const likeButtonRef = createRef<HTMLButtonElement>();
	const dislikeButtonRef = createRef<HTMLButtonElement>();

	const messageBox = (
		<div class={["messageBox", "aiMessage", props.isError && "aiMessageError"]}>
			<div className="messageAvatar">
				<IconAiAvatar />
			</div>

			<div class="messageBody">
				<div class="messageText">{props.text}</div>

				<div
					class="messageControlBox"
					hidden={!props.showControls}
					id={props.runId}
				>
					<button
						ref={likeButtonRef}
						class="messageControlButton likeButton"
						onClick={() =>
							handleLikeOrDislike(
								props.runId,
								FeedbackType.Like,
								likeButtonRef.current!,
								dislikeButtonRef.current!
							)
						}
					>
						<IconLike />
					</button>
					<button
						ref={dislikeButtonRef}
						class="messageControlButton dislikeButton"
						onClick={() =>
							handleLikeOrDislike(
								props.runId,
								FeedbackType.Dislike,
								likeButtonRef.current!,
								dislikeButtonRef.current!
							)
						}
					>
						<IconDislike />
					</button>
					<button
						class="messageControlButton copyButton"
						onClick={handleCopyButton(props.runId)}
					>
						<IconClipboard />
					</button>
				</div>
			</div>

			<p class="messageTime">{props.time}</p>
		</div>
	);

	return messageBox;
}

async function handleLikeOrDislike(
	runId: string,
	feedbackType: FeedbackType,
	likeButton: HTMLButtonElement,
	dislikeButton: HTMLButtonElement
) {
	const likeButtonSvg = likeButton.querySelector("svg");
	const dislikeButtonSvg = dislikeButton.querySelector("svg");

	let clickedButton: SVGSVGElement,
		oppositeButton: SVGSVGElement,
		clickedButtonElement: HTMLButtonElement,
		oppositeButtonElement: HTMLButtonElement;

	const feedbackValue = feedbackType === FeedbackType.Like ? "like" : "dislike";

	if (feedbackType === FeedbackType.Like) {
		clickedButton = likeButtonSvg;
		oppositeButton = dislikeButtonSvg;
		clickedButtonElement = likeButton;
		oppositeButtonElement = dislikeButton;
	} else {
		clickedButton = dislikeButtonSvg;
		oppositeButton = likeButtonSvg;
		clickedButtonElement = dislikeButton;
		oppositeButtonElement = likeButton;
	}

	// Disable both buttons
	likeButton.disabled = true;
	dislikeButton.disabled = true;

	// Determine final feedback (toggle off if already selected)
	const isSelected = clickedButton.classList.contains("selected");
	const finalFeedback = isSelected ? "none" : feedbackValue;

	try {
		const url = new URL(`${baseUrl}/ChatbotEventHandler.ashx`);
		url.searchParams.append("action", ServerEventType.Feedback);
		url.searchParams.append("run_id", runId);
		url.searchParams.append("feedback", finalFeedback);

		const response = await fetch(url);

		const updateFeedback = await response.json();
		if (!response.ok || !updateFeedback) {
			throw new Error("Feedback response is not ok.");
		}

		// Update UI based on feedback
		if (finalFeedback === "none") {
			// Remove selection from clicked button
			clickedButton.classList.remove("selected");
			clickedButtonElement.style.pointerEvents = "none";
			clickedButtonElement.innerHTML = "";
			clickedButtonElement.appendChild(
				feedbackType === FeedbackType.Like ? <IconLike /> : <IconDislike />
			);
		} else {
			// Add selection to clicked button
			clickedButton.classList.add("selected");
			clickedButtonElement.style.pointerEvents = "none";
			clickedButtonElement.innerHTML = "";
			clickedButtonElement.append(
				...(feedbackType === FeedbackType.Like
					? ((<IconLikeFilled />) as any)
					: ((<IconDislikeFilled />) as any))
			);

			// Remove selection from opposite button
			oppositeButton.classList.remove("selected");
			oppositeButtonElement.style.pointerEvents = "initial";
			oppositeButtonElement.innerHTML = "";
			oppositeButtonElement.append(
				...(feedbackType === FeedbackType.Like
					? ((<IconDislike />) as any)
					: ((<IconLike />) as any))
			);
		}
	} catch (error) {
		console.error("Error submitting feedback:", error);
	} finally {
		// Re-enable both buttons
		likeButton.disabled = false;
		dislikeButton.disabled = false;
		likeButton.style.opacity = "1";
		dislikeButton.style.opacity = "1";
		likeButton.style.cursor = "pointer";
		dislikeButton.style.cursor = "pointer";
	}
}

function handleCopyButton(runId: string) {
	return async () => {
		const messageControlBox = document.getElementById(runId);
		const messageBody = messageControlBox.closest(".messageBody");
		const messageText = messageBody.querySelector(".messageText");
		const textToCopy = messageText.textContent;

		try {
			await navigator.clipboard.writeText(textToCopy);

			// Show visual feedback
			const copyButton = messageControlBox.querySelector(".copyButton") as HTMLButtonElement;
			if (copyButton) {
				const originalHTML = copyButton.innerHTML;
				copyButton.replaceChildren(<span style="font-size: 0.8rem;">{i18n.copiedText}</span>);
				copyButton.disabled = true;

				setTimeout(() => {
					copyButton.innerHTML = originalHTML;
					copyButton.disabled = false;
				}, 2000);
			}
		} catch (error) {
			console.error("Failed to copy text:", error);
		}
	};
}
