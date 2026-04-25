class ApiConfig {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000',
  );

  static const String apiKey = String.fromEnvironment('API_KEY');

  static const String apiVersion = '/api/v1';
}
