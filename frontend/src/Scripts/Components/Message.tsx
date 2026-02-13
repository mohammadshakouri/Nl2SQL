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
import { config } from "../config.js";

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

	// Disable both buttons during processing
	likeButton.disabled = true;
	dislikeButton.disabled = true;
	likeButton.style.opacity = "0.5";
	dislikeButton.style.opacity = "0.5";

	// Check if already selected (toggle off)
	const isSelected = clickedButton.classList.contains("selected");
	
	try {
		// If clicking dislike and not already selected, prompt for corrected SQL
		if (feedbackType === FeedbackType.Dislike && !isSelected) {
			await handleDislikeFeedback(
				runId,
				clickedButton,
				oppositeButton,
				clickedButtonElement,
				oppositeButtonElement,
				likeButton,
				dislikeButton
			);
		} else if (feedbackType === FeedbackType.Like && !isSelected) {
			// Submit positive feedback
			await submitFeedback(runId, 1);
			
			// Update UI - select like button
			clickedButton.classList.add("selected");
			clickedButtonElement.innerHTML = "";
			clickedButtonElement.append(...((<IconLikeFilled />) as any));
			
			// Deselect opposite button
			oppositeButton.classList.remove("selected");
			oppositeButtonElement.innerHTML = "";
			oppositeButtonElement.append(...((<IconDislike />) as any));
		} else {
			// Toggle off - currently not supported by backend, but we can keep UI consistent
			clickedButton.classList.remove("selected");
			clickedButtonElement.innerHTML = "";
			clickedButtonElement.appendChild(
				feedbackType === FeedbackType.Like ? <IconLike /> : <IconDislike />
			);
		}
	} catch (error) {
		console.error("Error submitting feedback:", error);
		alert(i18n.feedbackError || "Failed to submit feedback. Please try again.");
	} finally {
		// Re-enable both buttons
		likeButton.disabled = false;
		dislikeButton.disabled = false;
		likeButton.style.opacity = "1";
		dislikeButton.style.opacity = "1";
	}
}

async function handleDislikeFeedback(
	runId: string,
	clickedButton: SVGSVGElement,
	oppositeButton: SVGSVGElement,
	clickedButtonElement: HTMLButtonElement,
	oppositeButtonElement: HTMLButtonElement,
	likeButton: HTMLButtonElement,
	dislikeButton: HTMLButtonElement
) {
	// Get the SQL query text from the message
	const messageControlBox = document.getElementById(runId);
	const messageBody = messageControlBox?.closest(".messageBody");
	const messageText = messageBody?.querySelector(".messageText");
	const originalSql = messageText?.textContent?.trim() || "";

	// Create and show modal for corrected SQL
	const modal = document.createElement("div");
	modal.className = "feedback-modal";
	modal.innerHTML = `
		<div class="feedback-modal-content">
			<div class="feedback-modal-header">
				<h3>${i18n.provideCorrectionTitle || "Provide Corrected SQL"}</h3>
				<button class="feedback-modal-close" aria-label="Close">×</button>
			</div>
			<div class="feedback-modal-body">
				<p>${i18n.provideCorrectionText || "Please provide the corrected SQL query and explain what was wrong:"}</p>
				
				<label for="corrected-sql">${i18n.correctedSqlLabel || "Corrected SQL Query:"}</label>
				<textarea 
					id="corrected-sql" 
					class="feedback-textarea" 
					rows="6"
					placeholder="${i18n.correctedSqlPlaceholder || "Enter the correct SQL query here..."}"
				>${originalSql}</textarea>
				
				<label for="feedback-comment">${i18n.commentLabel || "Comment (optional):"}</label>
				<textarea 
					id="feedback-comment" 
					class="feedback-textarea" 
					rows="3"
					placeholder="${i18n.commentPlaceholder || "Explain what was wrong with the original query..."}"
				></textarea>
			</div>
			<div class="feedback-modal-footer">
				<button class="feedback-modal-btn feedback-modal-cancel">${i18n.cancelButton || "Cancel"}</button>
				<button class="feedback-modal-btn feedback-modal-submit">${i18n.submitButton || "Submit Feedback"}</button>
			</div>
		</div>
	`;

	document.body.appendChild(modal);

	return new Promise<void>((resolve, reject) => {
		const closeBtn = modal.querySelector(".feedback-modal-close") as HTMLButtonElement;
		const cancelBtn = modal.querySelector(".feedback-modal-cancel") as HTMLButtonElement;
		const submitBtn = modal.querySelector(".feedback-modal-submit") as HTMLButtonElement;
		const correctedSqlTextarea = modal.querySelector("#corrected-sql") as HTMLTextAreaElement;
		const commentTextarea = modal.querySelector("#feedback-comment") as HTMLTextAreaElement;

		const closeModal = () => {
			modal.remove();
			reject();
		};

		closeBtn.onclick = closeModal;
		cancelBtn.onclick = closeModal;
		modal.onclick = (e) => {
			if (e.target === modal) closeModal();
		};

		submitBtn.onclick = async () => {
			const correctedSql = correctedSqlTextarea.value.trim();
			const comment = commentTextarea.value.trim();

			if (!correctedSql) {
				alert(i18n.correctedSqlRequired || "Please provide a corrected SQL query.");
				return;
			}

			submitBtn.disabled = true;
			submitBtn.textContent = i18n.submittingButton || "Submitting...";

			try {
				await submitFeedback(runId, -1, correctedSql, comment);
				
				// Update UI - select dislike button
				clickedButton.classList.add("selected");
				clickedButtonElement.innerHTML = "";
				clickedButtonElement.append(...((<IconDislikeFilled />) as any));
				
				// Deselect opposite button
				oppositeButton.classList.remove("selected");
				oppositeButtonElement.innerHTML = "";
				oppositeButtonElement.append(...((<IconLike />) as any));

				modal.remove();
				resolve();
			} catch (error) {
				console.error("Error submitting feedback:", error);
				alert(i18n.feedbackError || "Failed to submit feedback. Please try again.");
				submitBtn.disabled = false;
				submitBtn.textContent = i18n.submitButton || "Submit Feedback";
				reject(error);
			}
		};
	});
}

async function submitFeedback(
	runId: string,
	feedback: number,
	correctedSql?: string,
	comment?: string
): Promise<void> {
	const payload: any = {
		run_id: runId,
		feedback: feedback,
	};

	if (correctedSql) {
		payload.corrected_sql = correctedSql;
	}

	if (comment) {
		payload.comment = comment;
	}

	const response = await fetch(`${baseUrl}/feedback`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			"api-key": config.apiKey,
		},
		body: JSON.stringify(payload),
	});

	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(`Failed to submit feedback: ${errorText}`);
	}

	const result = await response.json();
	if (!result.success) {
		throw new Error("Feedback submission failed");
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
