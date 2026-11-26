import 'package:dio/dio.dart';

String friendlyErrorMessage(Object error) {
  if (error is DioException) {
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return 'Tiempo de espera agotado. Comprueba tu conexión.';
      case DioExceptionType.connectionError:
        return 'No se pudo conectar con el servidor.';
      case DioExceptionType.badResponse:
        final status = error.response?.statusCode;
        if (status == 404) return 'No se ha encontrado el producto.';
        if (status == 401) return 'No autorizado.';
        return 'Error del servidor (código $status).';
      case DioExceptionType.cancel:
        return 'Petición cancelada.';
      default:
        return 'Ha ocurrido un error inesperado.';
    }
  }
  return 'Ha ocurrido un error inesperado.';
}
