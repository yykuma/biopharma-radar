import { createFileRoute, redirect } from "@tanstack/react-router";
export const Route = createFileRoute("/feeds")({beforeLoad:()=>{throw redirect({to:"/$filter",params:{filter:"all"}})}});
