import 'package:dio/dio.dart';

import '../config/api_config.dart';
import '../models/price_history_entry.dart';
import '../models/product.dart';

class ApiService {
  ApiService() : _dio = _buildDio();

  final Dio _dio;

  static Dio _buildDio() {
    final dio = Dio(
      BaseOptions(
        baseUrl: '${ApiConfig.baseUrl}${ApiConfig.apiVersion}',
        connectTimeout: const Duration(seconds: 5),
        receiveTimeout: const Duration(seconds: 10),
        headers: const {'Accept': 'application/json'},
      ),
    );
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          if (ApiConfig.apiKey.isNotEmpty) {
            options.headers['X-API-Key'] = ApiConfig.apiKey;
          }
          handler.next(options);
        },
      ),
    );
    return dio;
  }

  Future<List<Product>> searchProducts(String query, {int limit = 20}) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/products',
      queryParameters: {'q': query, 'limit': limit},
    );
    final items = (resp.data!['items'] as List).cast<Map<String, dynamic>>();
    return items.map(Product.fromJson).toList();
  }

  Future<Product> getProduct(String id) async {
    final resp = await _dio.get<Map<String, dynamic>>('/products/$id');
    return Product.fromJson(resp.data!);
  }

  Future<List<PriceHistoryEntry>> getPriceHistory(String id) async {
    final resp = await _dio.get<List<dynamic>>('/products/$id/prices');
    return resp.data!
        .cast<Map<String, dynamic>>()
        .map(PriceHistoryEntry.fromJson)
        .toList();
  }
}
