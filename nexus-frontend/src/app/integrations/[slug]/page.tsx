import IntegrationDetailClient from "./integration-detail-client";

/** Static export requires a server entry for dynamic routes. */
export function generateStaticParams() { return [{ slug: "catalog" }]; }

export default function IntegrationDetailPage() { return <IntegrationDetailClient />; }

