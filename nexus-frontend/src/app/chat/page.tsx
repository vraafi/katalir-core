"use client";

// Alias /chat -> halaman chat utama.
//
// KENAPA: chat adalah fitur inti tetapi hanya bisa dicapai lewat "/" (atau
// "/?s=<id>"). Rute "/chat" memberi deep-link yang jelas, dan sekaligus
// memenuhi daftar halaman yang harus bisa dibuka langsung (`/chat`).
// Komponennya sengaja di-export ulang dari halaman utama supaya TIDAK ada dua
// implementasi chat yang bisa saling menyimpang (satu sumber kebenaran).
export { default } from "../page";
