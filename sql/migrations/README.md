# HANA Migrations

## Block A execution order

1. Run `001_analytics_extension_tables.sql`
2. Run `002_analytics_extension_views.sql`

## Why split the scripts?

SAP HANA can surface semantic errors when views are compiled in the same batch as table/column evolution. Splitting the scripts keeps the parser stable and makes each step easier to validate.

## Base schema dependency

Apply these scripts after `sql/hana_setup.sql`.

## Troubleshooting

If `002_analytics_extension_views.sql` fails with unresolved table errors (for example `MODEL_RUNS` or `MODEL_PREDICTIONS`), rerun step 1 and then step 2:

1. `001_analytics_extension_tables.sql`
2. `002_analytics_extension_views.sql`
