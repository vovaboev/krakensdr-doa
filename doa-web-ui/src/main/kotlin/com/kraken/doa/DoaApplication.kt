package com.kraken.doa

import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.runApplication

@SpringBootApplication
class DoaApplication

fun main(args: Array<String>) {
	runApplication<DoaApplication>(*args)
}