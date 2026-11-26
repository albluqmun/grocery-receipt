import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/utils/error_messages.dart';

DioException _dioError(DioExceptionType type, {int? statusCode}) {
  final requestOptions = RequestOptions(path: '/products');
  return DioException(
    requestOptions: requestOptions,
    type: type,
    response: statusCode != null
        ? Response(requestOptions: requestOptions, statusCode: statusCode)
        : null,
  );
}

void main() {
  group('friendlyErrorMessage', () {
    test('maps timeout errors', () {
      expect(
        friendlyErrorMessage(_dioError(DioExceptionType.connectionTimeout)),
        'Tiempo de espera agotado. Comprueba tu conexión.',
      );
    });

    test('maps connection errors', () {
      expect(
        friendlyErrorMessage(_dioError(DioExceptionType.connectionError)),
        'No se pudo conectar con el servidor.',
      );
    });

    test('maps 404 responses', () {
      expect(
        friendlyErrorMessage(
          _dioError(DioExceptionType.badResponse, statusCode: 404),
        ),
        'No se ha encontrado el producto.',
      );
    });

    test('maps 401 responses', () {
      expect(
        friendlyErrorMessage(
          _dioError(DioExceptionType.badResponse, statusCode: 401),
        ),
        'No autorizado.',
      );
    });

    test('maps other bad responses with the status code', () {
      expect(
        friendlyErrorMessage(
          _dioError(DioExceptionType.badResponse, statusCode: 500),
        ),
        'Error del servidor (código 500).',
      );
    });

    test('maps cancellation', () {
      expect(
        friendlyErrorMessage(_dioError(DioExceptionType.cancel)),
        'Petición cancelada.',
      );
    });

    test('falls back to a generic message for non-Dio errors', () {
      expect(friendlyErrorMessage(Exception('boom')), 'Ha ocurrido un error inesperado.');
    });
  });
}
