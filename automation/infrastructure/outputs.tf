output "infrastructure_endpoints" {
  value = {
    postgres = "localhost:5432"
    mongodb = "localhost:27017"
    elasticsearch = "localhost:9200"
    kafka = "localhost:9092"
    redis = "localhost:6379"
    clickhouse = "localhost:8123"
    mailhog = "localhost:8025"
  }
}
