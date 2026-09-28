import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/services/api_service.dart';

class _FakeHttpClientAdapter implements HttpClientAdapter {
  _FakeHttpClientAdapter(this.handler);

  final ResponseBody Function(RequestOptions options) handler;
  RequestOptions? lastOptions;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    lastOptions = options;
    return handler(options);
  }
}

ResponseBody _jsonBody(Object data, int statusCode) {
  return ResponseBody.fromString(
    jsonEncode(data),
    statusCode,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    },
  );
}

void main() {
  group('searchProducts', () {
    test('parses the items returned by the server', () async {
      final adapter = _FakeHttpClientAdapter(
        (options) => _jsonBody({
          'items': [
            {'id': 'p1', 'name': 'Leche entera'},
            {'id': 'p2', 'name': 'Leche desnatada'},
          ],
        }, 200),
      );
      final service = ApiService(httpClientAdapter: adapter);

      final products = await service.searchProducts('leche');

      expect(products.map((p) => p.id), ['p1', 'p2']);
      expect(adapter.lastOptions?.path, '/products');
      expect(adapter.lastOptions?.queryParameters, {'q': 'leche', 'limit': 20});
    });

    test('does not send X-API-Key when no key is configured', () async {
      final adapter = _FakeHttpClientAdapter(
        (options) => _jsonBody({'items': []}, 200),
      );
      final service = ApiService(httpClientAdapter: adapter);

      await service.searchProducts('leche');

      expect(adapter.lastOptions?.headers.containsKey('X-API-Key'), isFalse);
    });

    test('returns an empty list when there are no matches', () async {
      final adapter = _FakeHttpClientAdapter(
        (options) => _jsonBody({'items': []}, 200),
      );
      final service = ApiService(httpClientAdapter: adapter);

      final products = await service.searchProducts('inexistente');

      expect(products, isEmpty);
    });
  });

  group('getProduct', () {
    test('parses the product returned by the server', () async {
      final adapter = _FakeHttpClientAdapter(
        (options) => _jsonBody({'id': 'p1', 'name': 'Leche entera'}, 200),
      );
      final service = ApiService(httpClientAdapter: adapter);

      final product = await service.getProduct('p1');

      expect(product.id, 'p1');
      expect(product.name, 'Leche entera');
      expect(adapter.lastOptions?.path, '/products/p1');
    });

    test('throws when the server responds with a 404', () async {
      final adapter = _FakeHttpClientAdapter(
        (options) => _jsonBody({'detail': 'No encontrado'}, 404),
      );
      final service = ApiService(httpClientAdapter: adapter);

      await expectLater(
        service.getProduct('missing'),
        throwsA(
          isA<DioException>().having(
            (e) => e.response?.statusCode,
            'statusCode',
            404,
          ),
        ),
      );
    });
  });

  group('getPriceHistory', () {
    test('parses valid entries and skips malformed ones', () async {
      final adapter = _FakeHttpClientAdapter(
        (options) => _jsonBody([
          {'date': '2026-04-10', 'supermarket_name': 'Mercadona', 'unit_price': 1.35},
          {'date': 'not-a-date', 'supermarket_name': 'Carrefour', 'unit_price': 1.10},
        ], 200),
      );
      final service = ApiService(httpClientAdapter: adapter);

      final entries = await service.getPriceHistory('p1');

      expect(entries, hasLength(1));
      expect(entries.single.supermarketName, 'Mercadona');
      expect(adapter.lastOptions?.path, '/products/p1/prices');
    });

    test('returns an empty list when there is no history', () async {
      final adapter = _FakeHttpClientAdapter((options) => _jsonBody([], 200));
      final service = ApiService(httpClientAdapter: adapter);

      final entries = await service.getPriceHistory('p1');

      expect(entries, isEmpty);
    });
  });
}
