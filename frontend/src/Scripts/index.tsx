import { createRef } from "lestin/jsx-runtime";
import { animateSvgFillLoop } from "./animateFill.js";
import { Marked } from "marked";
import { IconAiAvatar, IconSend } from "./Icons.js";
import {
	AiIsRespondingMessage,
	AiMessage,
	SuggestionListItem,
	UserMessage,
} from "./Components/Message.js";
import { baseUrl, GetCurrentTimeString, ServerEventType } from "./enums.js";
import { i18n } from "./i18n.js";
import { Delay } from "./Utilities.js";

const marked = new Marked({
	gfm: true,
});

let timeout = null;
let isDialogOpen = false;
let isFirstOpen = true;
let isFirstToken = false;
let lastMessageRunId = "";
let isBotResponding = false;
let canSendMessage = false;
let eventSource: EventSource | undefined = undefined;
let threadId = "";
let streamBuffer = "";
let latestAiMessageElement: HTMLElement | undefined = undefined;

const dialogWrapperRef = createRef<HTMLDivElement>();
const chatContentRef = createRef<HTMLDivElement>();
const userInputRef = createRef<HTMLTextAreaElement>();
const sendButtonRef = createRef<HTMLButtonElement>();
const suggestionListRef = createRef<HTMLUListElement>();
const openDialogButtonRef = createRef<HTMLButtonElement>();

function OpenDialog() {
	isDialogOpen = true;
	dialogWrapperRef.current!.classList.add("visible");

	setTimeout(() => {
		userInputRef.current!.focus();
	}, 100);

	if (isFirstOpen) {
		isFirstOpen = false;
		DisableSendButton();
		setTimeout(async () => {
			AppendAiMessage(" ", "i1", false, false);
			await FakeStream(i18n.initialMessage, AppendToLastAiMessageText);
			EnableSendButton();
		}, 1500);
	}
}

function CloseDialog() {
	isDialogOpen = false;
	dialogWrapperRef.current!.classList.remove("visible");
}

function ToggleDialog() {
	openDialogButtonRef.current!.classList.add("openButtonRotate");
	setTimeout(
		() => openDialogButtonRef.current.classList.remove("openButtonRotate"),
		500
	);
	if (isDialogOpen) {
		return CloseDialog();
	}
	OpenDialog();
}

function ShrinkHeader() {
	wrapper.classList.add("shrink");
	setTimeout(() => {
		wrapper.classList.add("shrink2");
	}, 700);
}

function GetUserTypedText() {
	return userInputRef.current!.value.trim();
}

function EnableSendButton() {
	sendButtonRef.current!.disabled = false;
	sendButtonRef.current!.classList.remove("disableButton");
	canSendMessage = true;
}
function DisableSendButton() {
	sendButtonRef.current!.disabled = true;
	sendButtonRef.current!.classList.add("disableButton");
	canSendMessage = false;
}

function SendUserMessage(text = GetUserTypedText()) {
	if (!text || isBotResponding) return;

	AppendUserMessage(text);
	userInputRef.current!.value = "";
	isBotResponding = true;
	DisableSendButton();
	SendUserMessageToServer(text);
	clearResultsContainer();
}

function SendUserMessageToServer(text: string) {
	if (eventSource) eventSource.close();

	const url = new URL(`${baseUrl}/ChatbotEventHandler.ashx`);
	url.searchParams.append("action", ServerEventType.Message);
	url.searchParams.append("threadId", threadId);
	url.searchParams.append("message", text);

	eventSource = new EventSource(url);
	eventSource.onmessage = (event) => HandleServerEvent(event);
	eventSource.onerror = OnRespondError;
}

function OnRespondError() {
	AppendAiMessage(i18n.errorMessage, "i2", true, false);
	EnableSendButton();
	isBotResponding = false;
	if (eventSource) {
		eventSource.close();
		eventSource = undefined;
	}
}

async function HandleServerEvent(event: MessageEvent) {
	const data = JSON.parse(event.data);

	let messageTextElement =
		latestAiMessageElement?.getElementsByClassName("messageText")?.[0];
	const isRespondingElement = <AiIsRespondingMessage />;

	if (data.event === "on_start") {
		isFirstToken = true;
		isBotResponding = true;
		lastMessageRunId = data.run_id;
		threadId = data.thread_id;
		AppendAiMessage("", lastMessageRunId);
		messageTextElement =
			latestAiMessageElement.getElementsByClassName("messageText")[0];
		messageTextElement.append(isRespondingElement);
	} else if (data.event === "on_stream") {
		if (isFirstToken) {
			isBotResponding = true;
			isFirstToken = false;
			messageTextElement.replaceChildren();
		}
		AppendToLastAiMessageText(data.data);
	} else if (data.event === "on_end") {
		streamBuffer = "";
		isBotResponding = false;
		isFirstToken = false;
		lastMessageRunId = "";
		eventSource.close();
		EnableSendButton();
		latestAiMessageElement.classList.add("isComplete");
	} else if (data.event === "on_error") {
		messageTextElement.replaceChildren();
		DisableSendButton();
		isBotResponding = true;
		messageTextElement.textContent += data.data;
		lastMessageRunId = "";
		isBotResponding = false;
		eventSource.close();
	}
}

async function FakeStream(text: string, onInterval: (chunk: string) => void) {
	const textChunks = text.split(/ /g);
	for (const key in textChunks) {
		if (!Object.hasOwn(textChunks, key)) continue;

		const chunk = textChunks[key] + " ";
		if (!isBotResponding) {
			let delayDuration = 30 + Math.random() * 70;
			await Delay(delayDuration);
		}
		onInterval(chunk);
	}
	streamBuffer = "";
}

async function AppendToLastAiMessageText(chunk: string) {
	const messageTextElement =
		latestAiMessageElement.getElementsByClassName("messageText")[0];
	streamBuffer += chunk;
	messageTextElement.innerHTML = await marked.parse(
		streamBuffer.trim().replaceAll(/<br ?\/?>/g, "\n"),
		{
			gfm: true,
		}
	);
	messageTextElement.querySelectorAll("a").forEach((a) => {
		a.target = "_blank";
		a.rel = "noopener noreferrer";
	});
}

async function performSearch(query: string) {
	try {
		const url = new URL(`${baseUrl}/ChatbotEventHandler.ashx`);
		url.searchParams.append("action", ServerEventType.Search);
		url.searchParams.append("message", query);
		const response = await fetch(url);
		const data = await response.json();

		clearResultsContainer();
		const userInputText = GetUserTypedText();
		if (!userInputText) {
			return;
		}
		data.results.reverse().forEach((result) => {
			suggestionListRef.current!.prepend(
				<SuggestionListItem
					text={result.question}
					onClick={() => {
						SendUserMessage(result.question);

						setTimeout(() => {
							ShrinkHeader();
						}, 700);
					}}
				></SuggestionListItem>
			);
		});
	} catch (error) {
		console.error("Search failed:", error);
		// suggestionListRef.current!.append(<li>پیشنهادی برای ارائه پیدا نشد</li>);
	}
}

function clearResultsContainer() {
	const items = document.querySelectorAll(".suggestionItem");
	items.forEach((i) => {
		i.classList.add("isRemovingSuggestionItem");
		setTimeout(() => i.remove(), 900);
	});
}

const wrapper = (
	<div id="aiChatbotWrapper">
		<div class="buttonBox">
			<button
				class="openButton"
				ref={openDialogButtonRef}
				onClick={ToggleDialog}
			>
				<div class="aiLogoBack"></div>

				<svg
					id="aiLogoSparkle"
					viewBox="0 0 24 24"
					xmlns="http://www.w3.org/2000/svg"
				>
					<g
						fill="none"
						stroke="#fff"
						stroke-linejoin="round"
						stroke-width="1.5"
					>
						<path
							d="m17.503 14.751l.306.777c.3.763.904 1.366 1.666 1.667l.777.306l-.777.307c-.762.3-1.365.904-1.666 1.666l-.306.777l-.307-.777a2.96 2.96 0 0 0-1.666-1.666l-.777-.307l.777-.306a2.96 2.96 0 0 0 1.666-1.667z"
							fill="#fff"
						/>
						<path
							fill="#fff"
							d="M9.61 3.976c.08-.296.5-.296.58 0l.154.572a6.96 6.96 0 0 0 4.908 4.908l.572.154c.296.08.296.5 0 .58l-.572.154a6.96 6.96 0 0 0-4.908 4.908l-.154.572c-.08.296-.5.296-.58 0l-.154-.572a6.96 6.96 0 0 0-4.908-4.908l-.572-.154c-.296-.08-.296-.5 0-.58l.572-.154a6.96 6.96 0 0 0 4.908-4.908z"
						/>
					</g>
				</svg>
			</button>

			<div className="buttonTooltipBox">
				<div class="tooltipHeader">
					{i18n.chatBotTitle}
					<div class="tooltipIcon">
						<IconAiAvatar />
					</div>
				</div>

				<p>
					{i18n.tooltipSubtitle}
					<br />
					{i18n.tooltipText}
				</p>
			</div>
		</div>

		<div class="dialogWrapper" ref={dialogWrapperRef}>
			<div class="dialog">
				<div class="dialogHeader">
					<button class="openButton2">
						<div class="aiLogoBack2"></div>

						<svg
							id="aiLogoSparkle2"
							viewBox="0 0 24 24"
							xmlns="http://www.w3.org/2000/svg"
						>
							<g>
								<path d="m17.503 14.751l.306.777c.3.763.904 1.366 1.666 1.667l.777.306l-.777.307c-.762.3-1.365.904-1.666 1.666l-.306.777l-.307-.777a2.96 2.96 0 0 0-1.666-1.666l-.777-.307l.777-.306a2.96 2.96 0 0 0 1.666-1.667z" />
								<path d="M9.61 3.976c.08-.296.5-.296.58 0l.154.572a6.96 6.96 0 0 0 4.908 4.908l.572.154c.296.08.296.5 0 .58l-.572.154a6.96 6.96 0 0 0-4.908 4.908l-.154.572c-.08.296-.5.296-.58 0l-.154-.572a6.96 6.96 0 0 0-4.908-4.908l-.572-.154c-.296-.08-.296-.5 0-.58l.572-.154a6.96 6.96 0 0 0 4.908-4.908z" />
							</g>
						</svg>
					</button>

					<h2 class="dialogTitle">{i18n.chatBotTitle}</h2>
				</div>

				<div class="closeBox">
					<button class="closeButton" onClick={CloseDialog}>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">
							<path fill="currentColor" d="m0 1l1-1l7 7l-1 1M1 8L0 7l7-7l1 1" />
						</svg>
					</button>
				</div>

				<div class="dialogBody">
					<div className="chatAndSuggestions">
						<ul class="suggestionList" ref={suggestionListRef}></ul>
						<div class="chatContent" ref={chatContentRef}></div>
					</div>

					<div class="inputArea">
						<div class="sendButtonBox">
							<button
								class="sendButton"
								ref={sendButtonRef}
								onClick={() => {
									if (GetUserTypedText() === "" || isBotResponding) return;

									SendUserMessage();

									setTimeout(() => {
										ShrinkHeader();
									}, 700);
								}}
							>
								<IconSend />
							</button>
						</div>

						<div class="userInputBox">
							<textarea
								maxLength={250}
								ref={userInputRef}
								class="userInput"
								placeholder={i18n.inputPlaceholder}
								onKeyDown={(e) => {
									if (e.key === "Enter" && !e.shiftKey) {
										e.preventDefault();
										if (!canSendMessage) return;
										if (GetUserTypedText() === "" || isBotResponding) return;
										SendUserMessage();
										setTimeout(() => {
											ShrinkHeader();
										}, 700);
									}
								}}
								onInput={() => {
									clearTimeout(timeout);
									timeout = setTimeout(() => {
										const query = GetUserTypedText();
										if (String(query).length > 2) {
											performSearch(query);
										} else {
											clearResultsContainer();
										}
									}, 500);
								}}
							></textarea>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
);

function AppendAiMessage(
	text: string,
	runId: string,
	isError: boolean = false,
	showControls: boolean = true
) {
	latestAiMessageElement = (
		<AiMessage
			text={text}
			time={GetCurrentTimeString()}
			runId={runId}
			isError={isError}
			showControls={showControls}
		/>
	);

	chatContentRef.current!.prepend(latestAiMessageElement);
}

function AppendUserMessage(text: string) {
	chatContentRef.current!.prepend(
		<UserMessage text={text} time={GetCurrentTimeString()} />
	);
}

document.body.appendChild(wrapper);
const a = document.querySelector("#aiLogoSparkle2");
animateSvgFillLoop(a as unknown as SVGElement, 10_000);

const dialogHeader = document.getElementsByClassName("dialogHeader")?.[0];
const goToSimatic = document.getElementsByClassName("ticketButton")?.[0] as HTMLButtonElement;

if (goToSimatic) {
	goToSimatic.style.removeProperty("display");
	dialogHeader?.appendChild(goToSimatic);
}
