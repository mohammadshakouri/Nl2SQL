import { createRef } from "lestin/jsx-runtime";
import { i18n } from "./i18n.js";

export function IconClose() {
	return (
		<svg
			width="24px"
			height="24px"
			viewBox="0 0 18 18"
			xmlns="http://www.w3.org/2000/svg"
		>
			<g stroke="none" stroke-width="1" fill="none" fill-rule="evenodd">
				<g fill="#212121" fill-rule="nonzero">
					<path
						fill="currentColor"
						d="m8.244 12.155-4.95-4.947a1 1 0 1 1 1.415-1.415l4.294 4.291 4.293-4.279a.998.998 0 0 1 1.413.003c.39.392.388 1.025-.003 1.415l-5.002 4.986a.998.998 0 0 1-1.46-.054Z"
					></path>
				</g>
			</g>
		</svg>
	);
}

export function IconStop() {
	return (
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="24"
			height="24"
			fill="none"
			viewBox="0 0 24 24"
		>
			<path
				fill="currentColor"
				fill-rule="evenodd"
				d="M2 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10S2 17.523 2 12m7.5-3.5a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1v-5a1 1 0 0 0-1-1z"
				clip-rule="evenodd"
			></path>
		</svg>
	);
}

export function IconSend() {
	return (
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="32"
			height="32"
			viewBox="0 0 24 24"
		>
			<path
				fill="currentColor"
				fill-rule="evenodd"
				d="M3.402 6.673c-.26-2.334 2.143-4.048 4.266-3.042l11.944 5.658c2.288 1.083 2.288 4.339 0 5.422L7.668 20.37c-2.123 1.006-4.525-.708-4.266-3.042L3.882 13H12a1 1 0 1 0 0-2H3.883z"
				clip-rule="evenodd"
			/>
		</svg>
	);
}

export function IconLike() {
	return (
		<>
			<div class="aiMessageTooltip">{i18n.likeText}</div>
			<svg
				style="rotate: 180deg"
				xmlns="http://www.w3.org/2000/svg"
				width="24"
				height="24"
				fill="none"
				viewBox="0 0 24 24"
			>
				<path
					fill="currentColor"
					fill-rule="evenodd"
					d="M11.873 21.496a1 1 0 0 1-.992.496l-.454-.056A4 4 0 0 1 7.1 16.79L7.65 15h-.718c-2.637 0-4.553-2.508-3.859-5.052l1.364-5A4 4 0 0 1 8.296 2h9.709a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3h-2c-.26 0-.5.14-.628.364zM14.005 4h-5.71a2 2 0 0 0-1.929 1.474l-1.363 5A2 2 0 0 0 6.933 13h2.072a1 1 0 0 1 .955 1.294l-.949 3.084a2 2 0 0 0 1.462 2.537l3.167-5.543a2.72 2.72 0 0 1 1.364-1.182V5a1 1 0 0 0-1-1m3 9V5c0-.35-.06-.687-.171-1h1.17a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1z"
					clip-rule="evenodd"
				></path>
			</svg>
		</>
	);
}

export function IconDislike() {
	return (
		<>
			<div class="aiMessageTooltip">{i18n.dislikeText}</div>
			<svg
				style="transform: rotateY(180deg)"
				xmlns="http://www.w3.org/2000/svg"
				width="24"
				height="24"
				fill="none"
				viewBox="0 0 24 24"
			>
				<path
					fill="currentColor"
					fill-rule="evenodd"
					d="M11.873 21.496a1 1 0 0 1-.992.496l-.454-.056A4 4 0 0 1 7.1 16.79L7.65 15h-.718c-2.637 0-4.553-2.508-3.859-5.052l1.364-5A4 4 0 0 1 8.296 2h9.709a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3h-2c-.26 0-.5.14-.628.364zM14.005 4h-5.71a2 2 0 0 0-1.929 1.474l-1.363 5A2 2 0 0 0 6.933 13h2.072a1 1 0 0 1 .955 1.294l-.949 3.084a2 2 0 0 0 1.462 2.537l3.167-5.543a2.72 2.72 0 0 1 1.364-1.182V5a1 1 0 0 0-1-1m3 9V5c0-.35-.06-.687-.171-1h1.17a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1z"
					clip-rule="evenodd"
				></path>
			</svg>
		</>
	);
}

export function IconLikeFilled() {
	return (
		<>
			<div class="aiMessageTooltip">{i18n.likeText}</div>

			<svg
				style={{ rotate: "180deg" }}
				xmlns="http://www.w3.org/2000/svg"
				width="24"
				height="24"
				fill="none"
				viewBox="0 0 24 24"
			>
				<path
					fill="currentColor"
					d="M11.408 21.496a.99.99 0 0 1-1.06.485c-1.91-.384-3.073-2.342-2.5-4.212L8.697 15H6.986c-2.627 0-4.534-2.507-3.843-5.052l1.358-5A3.986 3.986 0 0 1 8.344 2h5.689a1.996 1.996 0 0 1 1.988 2v11h-.338a1 1 0 0 0-.865.504zM18.012 15A2.994 2.994 0 0 0 21 12V5c0-1.657-1.338-3-2.988-3h-.533c.34.588.533 1.271.533 2z"
				></path>
			</svg>
		</>
	);
}

export function IconDislikeFilled() {
	return (
		<>
			<div class="aiMessageTooltip">{i18n.dislikeText}</div>
			<svg
				style="transform: rotateY(180deg)"
				xmlns="http://www.w3.org/2000/svg"
				width="24"
				height="24"
				fill="none"
				viewBox="0 0 24 24"
			>
				<path
					fill="currentColor"
					d="M11.408 21.496a.99.99 0 0 1-1.06.485c-1.91-.384-3.073-2.342-2.5-4.212L8.697 15H6.986c-2.627 0-4.534-2.507-3.843-5.052l1.358-5A3.986 3.986 0 0 1 8.344 2h5.689a1.996 1.996 0 0 1 1.988 2v11h-.338a1 1 0 0 0-.865.504zM18.012 15A2.994 2.994 0 0 0 21 12V5c0-1.657-1.338-3-2.988-3h-.533c.34.588.533 1.271.533 2z"
				></path>
			</svg>
		</>
	);
}

export function IconClipboard() {
	return (
		<>
			<div class="aiMessageTooltip">{i18n.copiedText}</div>

			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="24"
				height="24"
				fill="none"
				viewBox="0 0 24 24"
			>
				<path
					fill="currentColor"
					fill-rule="evenodd"
					d="M7 5a3 3 0 0 1 3-3h9a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-2v2a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3v-9a3 3 0 0 1 3-3h2zm2 2h5a3 3 0 0 1 3 3v5h2a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1h-9a1 1 0 0 0-1 1zM5 9a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1z"
					clip-rule="evenodd"
				></path>
			</svg>
		</>
	);
}

export function IconWarning() {
	return (
		<svg
			version="1.0"
			xmlns="http://www.w3.org/2000/svg"
			width="96pt"
			height="96pt"
			viewBox="0 0 96 96"
			preserveAspectRatio="xMidYMid meet"
		>
			<g
				transform="translate(0,96) scale(0.1,-0.1)"
				fill="#000000"
				stroke="none"
			>
				<path d="M455 829 c-12 -6 -103 -147 -203 -315 -152 -252 -183 -310 -180 -336 5 -56 15 -58 408 -58 393 0 403 2 408 58 3 26 -28 84 -179 336 -121 202 -191 308 -207 315 -12 6 -24 11 -25 10 -1 0 -11 -5 -22 -10z m65 -329 l0 -100 -40 0 -40 0 0 100 0 100 40 0 40 0 0 -100z m0 -220 l0 -40 -40 0 -40 0 0 40 0 40 40 0 40 0 0 -40z" />
			</g>
		</svg>
	);
}

export function IconError() {
	return (
		<svg
			version="1.0"
			xmlns="http://www.w3.org/2000/svg"
			width="620pt"
			height="609pt"
			viewBox="0 0 620 609"
			preserveAspectRatio="xMidYMid meet"
		>
			<g
				transform="translate(0,609) scale(0.1,-0.1)"
				fill="#000000"
				stroke="none"
			>
				{" "}
				<path d="M2870 5994 c-438 -51 -727 -135 -1082 -316 -325 -165 -616 -391 -845 -653 -198 -226 -304 -381 -428 -625 -153 -302 -235 -562 -292 -920 -14 -91 -18 -174 -18 -405 0 -308 8 -386 60 -630 126 -588 463 -1162 910 -1552 226 -198 381 -304 625 -428 302 -153 562 -235 920 -292 165 -26 645 -26 810 0 358 57 618 139 920 292 244 124 399 230 625 428 262 229 488 520 653 845 159 312 241 569 299 932 14 91 18 174 18 405 0 308 -8 386 -60 630 -83 388 -269 797 -505 1110 -282 375 -617 659 -1018 863 -307 157 -553 237 -902 294 -98 15 -182 21 -390 23 -146 2 -281 1 -300 -1z m527 -789 c314 -41 597 -143 871 -313 39 -25 72 -46 72 -46 0 -1 -672 -673 -1493 -1494 l-1493 -1493 -45 73 c-221 354 -329 729 -329 1139 0 180 13 305 46 459 86 393 281 757 557 1039 345 351 779 570 1257 635 144 19 412 20 557 1z m1546 -987 c222 -364 327 -731 327 -1143 0 -1087 -799 -1993 -1880 -2130 -178 -23 -462 -17 -635 14 -249 44 -549 159 -764 292 l-83 52 1493 1493 c822 822 1495 1494 1496 1494 1 0 22 -33 46 -72z" />
			</g>
		</svg>
	);
}

export function IconTick() {
	return (
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="24"
			height="24"
			fill="none"
			viewBox="0 0 24 24"
		>
			<path
				fill="currentColor"
				fill-rule="evenodd"
				d="M18.063 5.674a1 1 0 0 1 .263 1.39l-7.5 11a1 1 0 0 1-1.533.143l-4.5-4.5a1 1 0 1 1 1.414-1.414l3.647 3.647 6.82-10.003a1 1 0 0 1 1.39-.263"
				clip-rule="evenodd"
			></path>
		</svg>
	);
}

export function IconAiAvatar() {
	return (
		<svg
			version="1.0"
			xmlns="http://www.w3.org/2000/svg"
			// width="134pt"
			// height="107pt"
			viewBox="0 0 134 107"
			preserveAspectRatio="xMidYMid meet"
		>
			<g
				transform="translate(0,107) scale(0.1,-0.1)"
				fill="currentColor"
				stroke="none"
			>
				<path d="M433 1016 l-26 -22 22 -62 c11 -34 21 -64 21 -66 0 -2 -29 -17 -63 -34 -81 -40 -159 -122 -197 -206 -21 -45 -36 -65 -52 -69 -13 -4 -37 -20 -53 -37 -26 -27 -30 -39 -30 -86 0 -51 3 -58 37 -90 22 -20 48 -34 63 -34 18 0 29 -9 44 -37 27 -53 85 -118 137 -154 76 -52 145 -70 289 -76 227 -10 338 21 440 121 34 33 72 80 83 102 17 33 28 43 55 48 18 3 47 20 63 37 25 26 29 38 29 84 0 46 -4 58 -30 85 -16 17 -40 33 -53 37 -16 4 -31 24 -52 69 -38 84 -116 166 -197 206 -34 17 -63 32 -63 34 0 2 10 32 21 66 l22 62 -26 22 c-37 32 -65 21 -89 -35 -11 -25 -22 -58 -25 -73 l-5 -28 -123 0 -122 0 -6 28 c-3 15 -14 48 -25 73 -24 56 -52 67 -89 35z m469 -269 c207 -93 252 -360 86 -514 -74 -67 -132 -83 -313 -83 -181 0 -239 16 -313 83 -192 177 -97 489 163 538 22 4 103 6 180 5 125 -3 146 -6 197 -29z" />
				<path d="M485 651 c-76 -34 -133 -133 -122 -212 8 -64 54 -129 112 -158 47 -25 58 -26 200 -26 142 0 153 1 200 26 58 29 104 94 112 158 11 79 -46 178 -122 212 -59 27 -321 27 -380 0z m79 -173 c17 -50 -42 -89 -78 -52 -19 19 -21 55 -4 72 7 7 26 12 43 10 22 -2 32 -10 39 -30z m309 11 c29 -47 -32 -101 -73 -64 -23 20 -25 37 -9 66 13 24 66 23 82 -2z" />
			</g>
		</svg>
	);
}

export function SuggestionIcon() {
	return (
		<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
			<g
				fill="none"
				stroke="#521e75ff"
				stroke-linejoin="round"
				stroke-width="1.5"
			>
				<path
					d="m17.503 14.751l.306.777c.3.763.904 1.366 1.666 1.667l.777.306l-.777.307c-.762.3-1.365.904-1.666 1.666l-.306.777l-.307-.777a2.96 2.96 0 0 0-1.666-1.666l-.777-.307l.777-.306a2.96 2.96 0 0 0 1.666-1.667z"
					fill="#7c3251ff"
				/>
				<path
					fill="#5452a5ff"
					d="M9.61 3.976c.08-.296.5-.296.58 0l.154.572a6.96 6.96 0 0 0 4.908 4.908l.572.154c.296.08.296.5 0 .58l-.572.154a6.96 6.96 0 0 0-4.908 4.908l-.154.572c-.08.296-.5.296-.58 0l-.154-.572a6.96 6.96 0 0 0-4.908-4.908l-.572-.154c-.296-.08-.296-.5 0-.58l.572-.154a6.96 6.96 0 0 0 4.908-4.908z"
				/>
			</g>
		</svg>
	);
}